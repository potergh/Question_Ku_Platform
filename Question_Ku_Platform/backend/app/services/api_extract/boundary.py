"""行清单 -> LLM 边界判定 -> list[QuestionRecord]。

为什么边界判定权要交给 LLM：实测 25 页讲义上，现有几何切题（ANCHOR_RE + LIS
选题号链）内容覆盖率只有 46%，p3-p14 共 12 页没有任何题卡、8922 字正文被静默
丢弃，而 CompletenessValidator 报告全绿通过。根因是讲义用「【例1】」编号、板块
处题号重启（例题解析 / 随堂检测 各自从 1 开始），正则认不出，LIS 又只能选一条
单调链，于是拼出一条「伪连续」序列。

本模块的输出契约是 list[QuestionRecord] —— 与几何通道同一个类型，因此
QuestionCropper.crop / FigureExtractor.extract_all / CompletenessValidator.validate
全部零改动复用（crop 只读 record.segments，extract_all 只按 record.number 索引）。

坐标不让 LLM 回传：浮点数容易被抄错，改为只回传行清单里的 line_id（整数），
由本模块反查 (page_index, y0/y1) 再算裁剪矩形。
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf as fitz

from physics_paper_splitter.figures import paired_image_rects, recurring_xrefs
from physics_paper_splitter.lines import (
    TextLine,
    extract_line_inventory,
    to_prompt_text,
)
from physics_paper_splitter.models import CropSegment, QuestionRecord
from physics_paper_splitter.splitter import QuestionSplitter

from . import ExtractCancelled
from .prompts import (
    BOUNDARY_SYSTEM,
    PAGE_TRANSCRIBE_SYSTEM,
    boundary_system_prompt,
    boundary_user_text,
    page_transcribe_user_text,
)
from .vlm_client import VLMError, call_vlm_json

logger = logging.getLogger(__name__)

# 分批预算：单批行清单的字符上限。25 页讲义不分批会顶穿上下文。
BATCH_CHAR_BUDGET = 24000
# 单批页数硬上限，与字符预算取先触发者。
MAX_BATCH_PAGES = 10
# 批间重叠页数：跨批题目在两个批次里都能被看到，靠 start_line 归并。
OVERLAP_PAGES = 1
# 批次并发上限。批次之间互不依赖（归并靠 owned_range），单批约 25s，
# 串行跑 4 批就是 100s 白等。
# 实测：3 并发时 4 批 35s；提到 4 并发反而变 54.6s（每次调用延迟从 ~35s 涨到 ~54.6s，
# 日志里没有任何 429/重试），说明是端点在并发下的排队行为，加大并发只会更慢。
# 这个数不是"越多越快"的旋钮，调之前必须实测。
BOUNDARY_CONCURRENCY = 3

# 裁剪留白，与 splitter.build_records 的 anchor.y - 4.0 / effective_end[1] - 5.0 对齐。
TOP_PADDING = 4.0
GAP = 5.0
MIN_SEGMENT_HEIGHT = 4.0

# 边界避让插图（见 avoid_figure_cuts）。尺寸区间用来筛掉"不是插图"的对象：
# 太扁的是分隔线与表格框线，太大的是页面底纹或边框。
FIGURE_MIN_HEIGHT = 4.0
FIGURE_MAX_HEIGHT = 500.0
FIGURE_MAX_WIDTH = 580.0
# 判定"横跨边界"的容差：图形必须真的两侧都伸出边界这么多才算，避免边界
# 恰好贴着图形边缘时被当成切穿（那本来就没切到东西）。
FIGURE_STRADDLE_TOL = 1.0
# 让开后保留的余量。边界正好压在图形顶边上时，栅格化仍会把最上面那一两像素
# 行带进题卡（实测第 27 题会残留四个细点），留一点余量才真正干净。
FIGURE_CLEARANCE = 1.0
# 单次避让的最大位移。跨度更大说明不是"图的一角被切进来"，而是别的问题，
# 不该由这里自动动手。
FIGURE_SNAP_MAX_SHIFT = 60.0

# 扫描页整页转写的渲染分辨率：够 VLM 认字即可，太高只会拖慢与撑大请求体。
TRANSCRIBE_DPI = 150
# 整页转写的并发上限。实测单页 30s（1160 输出 token，端点约 41 tok/s），
# 而 8 页扫描件串行就是 4 分钟——这些页彼此完全独立，没有理由排队。
# 实测（8 页无文字层）：4 并发 95.5s → 8 并发 56.3s，是净收益，保留。
TRANSCRIBE_CONCURRENCY = 8
# PyMuPDF 的 Document 不是线程安全的，渲染必须串行（见 _render_page）。
_RENDER_LOCK = asyncio.Lock()

# 题号锚点校正：允许把题区间起点往前挪的最大行数。
# 只修「差一两行」的偏差；跨度更大说明模型判的是另一道题，不该自动动手。
ANCHOR_MAX_SHIFT = 3
# 行首题号：前缀最多 4 个非数字字符（「22．」「（多选）11．」「【例1】」都命中）。
LEADING_NUMBER_RE = re.compile(r"^\D{0,4}?(\d{1,3})\s*[．.、]")

# 只借 QuestionSplitter 的 _content_bottom（贴页脚求正文下边界）与边距常量，
# 保证与几何通道裁出来的题卡视觉一致。
_SPLITTER = QuestionSplitter()


@dataclass(slots=True)
class QuestionSpan:
    """一道题在行清单上的区间。qid 是全局序号 1..N。

    label / section / qtype / score 不放进 QuestionRecord（那是几何通道的共用类型，
    不宜再堆字段），由 BoundaryResult.spans 与 records 按下标一一对应地带出。
    """

    qid: int
    label: str
    section: str | None
    qtype: str | None
    score: float | None
    start_line: int
    end_line: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class NonQuestionRegion:
    """显式归类为非题目的行区间：卷首信息、章节标题、说明、文末答案区。

    这些行会进 coverage_audit 的 excluded_line_ids，不计入覆盖率分母 ——
    没有这个机制，本就不属于题卡的内容会把覆盖率拖到阈值以下造成误阻断。
    """

    start_line: int
    end_line: int
    kind: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class BoundaryResult:
    """边界判定的完整产出。"""

    doc_kind: str = "paper"
    spans: list[QuestionSpan] = field(default_factory=list)
    regions: list[NonQuestionRegion] = field(default_factory=list)
    records: list[QuestionRecord] = field(default_factory=list)
    # 非题目区域覆盖的 line_id，直接喂给 coverage_audit。
    excluded_line_ids: set[int] = field(default_factory=set)
    # 文末答案区的行区间，answers.py 的第二答案源从这里取。
    answer_key_line_ids: set[int] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "doc_kind": self.doc_kind,
            "question_count": len(self.spans),
            "spans": [span.to_dict() for span in self.spans],
            "regions": [region.to_dict() for region in self.regions],
            "excluded_line_count": len(self.excluded_line_ids),
            "warnings": self.warnings,
        }


# ── 行清单构建（含扫描页降级转写）────────────────────────────────────


def _page_lines(lines: list[TextLine]) -> dict[int, list[TextLine]]:
    """按页分组并按视觉顺序排序。"""
    grouped: dict[int, list[TextLine]] = {}
    for line in lines:
        grouped.setdefault(line.page_index, []).append(line)
    for page in grouped.values():
        page.sort(key=lambda item: (item.y0, item.x0))
    return grouped


def _renumber(lines: list[TextLine]) -> list[TextLine]:
    """按 (页, y, x) 排序后重排 line_id，保证全清单单调递增。"""
    ordered = sorted(lines, key=lambda item: (item.page_index, item.y0, item.x0))
    for order, line in enumerate(ordered, start=1):
        line.line_id = order
    return ordered


async def _render_page(doc: fitz.Document, page_index: int, out_dir: Path) -> Path:
    """把整页渲染成 PNG，供 VLM 转写。

    CPU 密集，放线程池；但 PyMuPDF 的**同一个 Document 不能被多个线程并发访问**，
    所以这里用锁把渲染串起来。代价极小：渲染是百毫秒级，而它服务的转写调用是
    30 秒级——串行渲染换并发转写，净赚。
    """

    def _work() -> Path:
        pix = doc[page_index].get_pixmap(dpi=TRANSCRIBE_DPI, alpha=False, colorspace=fitz.csRGB)
        path = out_dir / f"page_{page_index + 1:03d}.png"
        pix.save(str(path))
        return path

    async with _RENDER_LOCK:
        return await asyncio.get_event_loop().run_in_executor(None, _work)


async def transcribe_page(
    config: dict,
    doc: fitz.Document,
    page_index: int,
    out_dir: Path,
) -> list[TextLine]:
    """整页转写：把没有可用文字层的页面交给视觉模型，产出合成的 TextLine。

    y 由模型给的 y_ratio 乘页高还原，精度足够裁卡（题卡边界本来就要留白），
    且不要求模型输出任何浮点坐标之外的东西。
    """
    image_path = await _render_page(doc, page_index, out_dir)
    try:
        payload = await call_vlm_json(
            config,
            system=PAGE_TRANSCRIBE_SYSTEM,
            user_text=page_transcribe_user_text(page_index + 1),
            image_paths=[image_path],
        )
    finally:
        image_path.unlink(missing_ok=True)

    page = doc[page_index]
    height = float(page.rect.height)
    width = float(page.rect.width)
    rows = payload.get("lines") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise VLMError(f"第 {page_index + 1} 页转写返回结构异常: {str(payload)[:200]}")

    parsed: list[tuple[float, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            ratio = float(row.get("y_ratio"))
        except (TypeError, ValueError):
            ratio = 0.5
        parsed.append((min(max(ratio, 0.0), 1.0) * height, text))
    parsed.sort(key=lambda item: item[0])

    synthesized: list[TextLine] = []
    for index, (y0, text) in enumerate(parsed):
        # 行高用到下一行的间距估算，最后一行退化为页高的 3%。
        next_y0 = parsed[index + 1][0] if index + 1 < len(parsed) else y0 + height * 0.03
        y1 = min(max(next_y0 - 1.0, y0 + 1.0), height)
        synthesized.append(
            TextLine(
                line_id=-1,
                page_index=page_index,
                y0=round(y0, 2),
                y1=round(y1, 2),
                x0=0.0,
                x1=round(width, 2),
                text=text,
            )
        )
    return synthesized


async def build_line_inventory(
    config: dict,
    doc: fitz.Document,
    *,
    vlm_pages: set[int] | None = None,
    cancel_check=None,
) -> tuple[list[TextLine], list[str]]:
    """构建整份文档的行清单，返回 (行清单, 告警)。

    文字层可用的页走 PyMuPDF（零 Token）；inspector 判定 route == "vlm" 的页
    交给视觉模型整页转写后合成 TextLine。两条来源在同一个清单里按 (页, y)
    归并重排 line_id，下游模块完全感知不到差异。
    """
    warnings: list[str] = []
    native = extract_line_inventory(doc)
    targets = vlm_pages or set()
    if not targets:
        return _renumber(native), warnings

    kept = [line for line in native if line.page_index not in targets]
    with tempfile.TemporaryDirectory(prefix="api_extract_page_") as tmp:
        out_dir = Path(tmp)
        semaphore = asyncio.Semaphore(TRANSCRIBE_CONCURRENCY)

        async def _transcribe_one(page_index: int):
            """转写单页。失败不回抛，把异常对象交给调用方记账：
            单页失败不该拖垮整份文档（该页会因无行成为孤儿页，由审计如实阻断）。"""
            async with semaphore:
                if cancel_check and await cancel_check():
                    raise ExtractCancelled()
                try:
                    return await transcribe_page(config, doc, page_index, out_dir)
                except VLMError as exc:
                    logger.warning("transcribe page %s failed: %s", page_index + 1, exc)
                    return exc

        # 这些页彼此完全独立，串行只是实现遗漏：8 页 × 30s = 4 分钟白等。
        wanted = sorted(targets)
        outcomes = await asyncio.gather(*(_transcribe_one(page) for page in wanted))
        for page_index, outcome in zip(wanted, outcomes):
            if isinstance(outcome, VLMError):
                warnings.append(f"第 {page_index + 1} 页整页转写失败，该页内容缺失：{outcome}")
                continue
            if not outcome:
                warnings.append(f"第 {page_index + 1} 页整页转写未返回任何文字行。")
            kept.extend(outcome)

    return _renumber(kept), warnings


# ── 分批 ─────────────────────────────────────────────────────────────


def plan_batches(lines: list[TextLine]) -> list[tuple[int, int]]:
    """按页窗口切批，返回 [(首页索引, 末页索引)]。

    字符预算与页数上限取先触发者；批间重叠 OVERLAP_PAGES 页，让跨批题目在
    两个批次里都可见。单页超预算时该页自成一批，重叠自然退化为 0。
    """
    if not lines:
        return []
    page_ids = sorted({line.page_index for line in lines})
    chars_per_page: dict[int, int] = {}
    for line in lines:
        chars_per_page[line.page_index] = chars_per_page.get(line.page_index, 0) + len(line.text) + 16

    batches: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(page_ids):
        total = 0
        end = cursor
        while end < len(page_ids) and (end - cursor) < MAX_BATCH_PAGES:
            cost = chars_per_page[page_ids[end]]
            # 首批必须至少吃下一页，否则单页超预算时会死循环。
            if total + cost > BATCH_CHAR_BUDGET and end > cursor:
                break
            total += cost
            end += 1
        batches.append((page_ids[cursor], page_ids[end - 1]))
        if end >= len(page_ids):
            break
        cursor = max(cursor + 1, end - OVERLAP_PAGES)
    return batches


def _batch_line_ids(lines: list[TextLine], first_page: int, last_page: int) -> list[TextLine]:
    return [line for line in lines if first_page <= line.page_index <= last_page]


def _owned_ranges(batches: list[tuple[int, int]], lines: list[TextLine]) -> list[tuple[int, int]]:
    """每批「拥有」的 line_id 半开区间 (下界, 上界]。

    用 line_id 而不是页码来划分归属：单页超预算时批间不重叠，按页排除首批
    会把整页题目误删。按 line_id 切分则每一行恰好归属一个批次。
    """
    owned: list[tuple[int, int]] = []
    previous_end = 0
    for first_page, last_page in batches:
        batch_lines = _batch_line_ids(lines, first_page, last_page)
        last_id = max((line.line_id for line in batch_lines), default=previous_end)
        owned.append((previous_end, last_id))
        previous_end = last_id
    return owned


# ── LLM 响应解析 ─────────────────────────────────────────────────────


def _as_line_id(value, line_index: dict[int, TextLine]) -> int | None:
    try:
        line_id = int(value)
    except (TypeError, ValueError):
        return None
    return line_id if line_id in line_index else None


def _parse_questions(payload, line_index: dict[int, TextLine]) -> tuple[list[dict], list[str]]:
    """解析并校验 questions 数组，返回 (合法条目, 丢弃原因)。"""
    rows = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], ["响应缺少 questions 数组"]

    valid: list[dict] = []
    dropped: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            dropped.append(f"非对象条目被丢弃: {str(row)[:60]}")
            continue
        start = _as_line_id(row.get("start_line"), line_index)
        end = _as_line_id(row.get("end_line"), line_index)
        if start is None or end is None:
            dropped.append(
                f"line_id 越界被丢弃: {row.get('start_line')}..{row.get('end_line')} "
                f"(label={row.get('label')})"
            )
            continue
        if end < start:
            start, end = end, start
            dropped.append(f"区间倒置已自动纠正: {start}..{end}")
        score = row.get("score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        section = row.get("section")
        valid.append(
            {
                "label": str(row.get("label") or "").strip(),
                "section": str(section).strip() if section else None,
                "qtype": str(row.get("type") or "").strip() or None,
                "score": score,
                "start_line": start,
                "end_line": end,
            }
        )
    return valid, dropped


def _parse_regions(payload, line_index: dict[int, TextLine]) -> list[dict]:
    """解析 non_question_regions；kind 未知的归为 other 而不是丢弃。"""
    rows = payload.get("non_question_regions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    known = {"cover", "section_header", "instruction", "answer_key", "other"}
    valid: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = _as_line_id(row.get("start_line"), line_index)
        end = _as_line_id(row.get("end_line"), line_index)
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        kind = str(row.get("kind") or "other").strip()
        valid.append(
            {"start_line": start, "end_line": end, "kind": kind if kind in known else "other"}
        )
    return valid


# ── 跨批归并 ─────────────────────────────────────────────────────────


def _merge_reports(
    reports: list[tuple[tuple[int, int], list[dict], list[dict]]],
    total_lines: int,
    warnings: list[str],
) -> tuple[list[dict], list[dict]]:
    """把各批次的题目与非题目区间归并成全局不重叠的有序列表。

    归并规则：
    - 归属：一道题由「其 start_line 落在该批 owned 区间内」的那一批负责，
      重叠页上的重复上报因此被自然去掉。
    - 续尾：同一 start_line 在后续批次里被报出更大的 end_line 时取最大值，
      这样跨批长题（起始在重叠页、尾巴只在下一批可见）不会在中途被截断。
    - 冲突：归并后若仍有区间重叠，截断前一条并告警；截断到空则丢弃。
    """
    best_end: dict[int, int] = {}
    for _, questions, regions in reports:
        for row in questions + regions:
            start = row["start_line"]
            best_end[start] = max(best_end.get(start, start), row["end_line"])

    def collect(pick) -> list[dict]:
        """pick(owned, entries) -> 该批次里需要参与归并的条目。"""
        accepted: list[dict] = []
        seen: set[int] = set()
        for owned, questions, regions in reports:
            for row in pick(owned, questions, regions):
                start = row["start_line"]
                if not (owned[0] < start <= owned[1]) or start in seen:
                    continue
                seen.add(start)
                merged = dict(row)
                merged["end_line"] = min(best_end.get(start, row["end_line"]), total_lines)
                accepted.append(merged)
        accepted.sort(key=lambda row: (row["start_line"], row["end_line"]))
        return accepted

    questions = collect(lambda owned, q, r: q)
    regions = collect(lambda owned, q, r: r)

    def resolve_overlaps(entries: list[dict], what: str) -> list[dict]:
        resolved: list[dict] = []
        for row in entries:
            if resolved and row["start_line"] <= resolved[-1]["end_line"]:
                previous = resolved[-1]
                previous["end_line"] = row["start_line"] - 1
                if previous["end_line"] < previous["start_line"]:
                    dropped = resolved.pop()
                    warnings.append(
                        f"{what}区间重叠，整条丢弃：line {dropped['start_line']}..{dropped['end_line']}"
                    )
                    continue
                warnings.append(
                    f"{what}区间重叠，前一条被截断到 line {previous['end_line']}"
                )
            resolved.append(row)
        return resolved

    questions = resolve_overlaps(questions, "题目")
    regions = resolve_overlaps(regions, "非题目区域")

    # 题目区间不得与非题目区间重叠：题目优先（内容进题卡比归类更重要）。
    if questions and regions:
        trimmed: list[dict] = []
        for region in regions:
            clash = any(
                not (region["end_line"] < q["start_line"] or region["start_line"] > q["end_line"])
                for q in questions
            )
            if clash:
                warnings.append(
                    f"非题目区域 line {region['start_line']}..{region['end_line']} "
                    f"({region['kind']}) 与题目区间重叠，已忽略该区域"
                )
                continue
            trimmed.append(region)
        regions = trimmed

    return questions, regions


def _doc_kind(reports_kinds: list[str], hint: str | None) -> str:
    if hint in ("paper", "handout"):
        return hint
    handout = sum(1 for kind in reports_kinds if kind == "handout")
    if handout * 2 > len(reports_kinds):
        return "handout"
    return reports_kinds[0] if reports_kinds else "paper"


def _report_uncovered(
    line_index: dict[int, TextLine],
    questions: list[dict],
    regions: list[dict],
    warnings: list[str],
) -> None:
    """LLM 被要求对每一行负责；漏掉的行在这里如实报出来。

    漏行本身不一定阻断（后续裁卡时会被相邻区间的留白带进题卡），但必须
    可见 —— 静默丢内容正是旧通道的致命伤。
    """
    covered: set[int] = set()
    for row in questions + regions:
        covered.update(range(row["start_line"], row["end_line"] + 1))
    missing = sorted(set(line_index) - covered)
    if not missing:
        return
    preview = ", ".join(f"#{i}" for i in missing[:10])
    warnings.append(
        f"有 {len(missing)} 行未被任何区间覆盖（{preview}{'…' if len(missing) > 10 else ''}），"
        f"例如：{line_index[missing[0]].text[:40]}"
    )


# ── 区间 -> 裁剪矩形 -> QuestionRecord ───────────────────────────────


def _cut_line_id(
    end_line: int,
    questions: list[dict],
    regions: list[dict],
) -> int | None:
    """该题之后最近一个区间的起始行；决定末页下边界停在哪儿。"""
    candidates = [
        row["start_line"]
        for row in questions + regions
        if row["start_line"] > end_line
    ]
    return min(candidates) if candidates else None


def _figures_in_band(page: fitz.Page, band: fitz.Rect, recurring: set[int]) -> list[fitz.Rect]:
    """落在 band 区间内的位图原矩形（已剔除跨页复现的装饰图与过小的碎片）。"""
    rects: list[fitz.Rect] = []
    for image_info in page.get_images(full=True):
        xref = image_info[0]
        if xref in recurring:
            continue
        try:
            image_rects = page.get_image_rects(xref)
        except Exception:
            # 被遮罩或损坏的图片对象取不到矩形，跳过不影响其余内容。
            continue
        for image_rect, _clip in paired_image_rects(image_rects, band):
            rects.append(image_rect)
    return rects


def _build_records(
    doc: fitz.Document,
    line_index: dict[int, TextLine],
    lines_by_page: dict[int, list[TextLine]],
    questions: list[dict],
    regions: list[dict],
    question_page_count: int | None = None,
) -> list[QuestionRecord]:
    """把题目区间换算成裁剪片段。

    末页下边界的取法（沿用 splitter.build_records 的思路）：
    - 同一页上还有后续区间 -> 停在它的起始行上方 GAP 处，避免带入下一题首行；
    - 否则 -> 停在该页正文下边界（贴页脚），把题末插图一并收进来。
    上边界取「正文上边距」与「首行上方留白」的较大者：题目不在页顶时从题目
    首行上方起裁，题目紧贴页顶时用页边距兜底，两种情况下都不会裁掉本题内容，
    也不会把同页前面的题目卷进来。跨页续段则直接从页顶起裁。

    另外补一段「尾部插图」：题干排到页底、插图被挤到下一页顶部时（典型是
    「如图所示」题），图既不在按行区间算出的片段里，也不会跟任何题目矩形相交，
    会直接丢失。这里把「本题结束之后、下一区间开始之前」的插图并进来。
    """
    top_margin = _SPLITTER.top_margin
    side_margin = _SPLITTER.side_margin
    recurring = recurring_xrefs(doc)
    last_question_page = (
        question_page_count - 1 if question_page_count else doc.page_count - 1
    )
    records: list[QuestionRecord] = []

    for order, row in enumerate(questions, start=1):
        start = line_index[row["start_line"]]
        end = line_index[row["end_line"]]
        cut_id = _cut_line_id(row["end_line"], questions, regions)
        cut = line_index[cut_id] if cut_id is not None else None
        segments: list[CropSegment] = []

        for page_index in range(start.page_index, end.page_index + 1):
            page = doc[page_index]
            on_page = [
                line
                for line in lines_by_page.get(page_index, [])
                if row["start_line"] <= line.line_id <= row["end_line"]
            ]
            # 该页只有插图没有文字行时仍要出片段，否则跨页题的整页图会丢。
            if page_index == start.page_index:
                # 首段从本题首行上方起裁，但不越过正文上边距。
                # 这里必须用 max：曾经写成 min，导致只要题目不在页顶，
                # 上边界就一律落到 top_margin，把页面上前面几道题整段裁进本题卡图
                # （实测第 16 题卡图高 725pt = 整页内容高度）。
                first_y0 = on_page[0].y0 if on_page else top_margin + TOP_PADDING
                y0 = max(top_margin, first_y0 - TOP_PADDING)
            else:
                # 跨页续段：内容从上一页延续过来，页面顶部仍属于本题，从页顶起裁。
                y0 = top_margin

            bottom = _SPLITTER._content_bottom(page)
            if cut is not None and cut.page_index == page_index:
                y1 = min(cut.y0 - GAP, bottom)
            else:
                y1 = bottom
            # 本题在该页的末行必须收进来。_content_bottom 对扫描件没有文字层可探页脚，
            # 会退化成「页高 - bottom_margin(82)」；实测河东卷页高只有 792pt，
            # 于是每页下边界算成 710，而真实末行在 743~792 —— 全卷每页都被切掉
            # 33~82pt，第 7 题更因 y1 < y0 连片段都没生成（卡图缺失）。
            if on_page:
                y1 = max(y1, min(on_page[-1].y1 + TOP_PADDING, page.rect.height))
            if y1 - y0 < MIN_SEGMENT_HEIGHT:
                continue

            segments.append(
                CropSegment(
                    page_index=page_index,
                    x0=side_margin,
                    y0=y0,
                    x1=page.rect.width - side_margin,
                    y1=y1,
                )
            )

        # 尾部插图：题干结束之后、下一区间开始之前仍属于本题的插图。
        # 下探范围同时受「下一区间起始页」与「题目页总数」约束 —— 后者是必须的，
        # 否则最后一题会把整段答案/解析页都扫进来。
        tail_last = cut.page_index if cut is not None else last_question_page
        tail_last = min(tail_last, last_question_page)
        for page_index in range(end.page_index + 1, tail_last + 1):
            page = doc[page_index]
            bottom = _SPLITTER._content_bottom(page)
            # 停在下一区间首行上方 1pt：图不是文字，不需要再留 GAP，
            # 但也不能把下一题的首行裁进来。
            cap = min(cut.y0 - 1.0, bottom) if (cut and cut.page_index == page_index) else bottom
            band = fitz.Rect(0, top_margin, page.rect.width, cap)
            figures = _figures_in_band(page, band, recurring)
            if not figures:
                continue
            y1 = min(max(rect.y1 for rect in figures) + TOP_PADDING, cap)
            if y1 - top_margin < MIN_SEGMENT_HEIGHT:
                continue
            segments.append(
                CropSegment(
                    page_index=page_index,
                    x0=side_margin,
                    y0=top_margin,
                    x1=page.rect.width - side_margin,
                    y1=y1,
                )
            )

        # end_page 跟随实际片段，否则 JSON 会声称卡图止于第 6 页、
        # 而片段其实已经铺到第 7 页。
        last_segment = segments[-1] if segments else None
        records.append(
            QuestionRecord(
                number=order,
                filename=f"Q{order:03d}.webp",
                start_page=start.page_index + 1,
                end_page=(last_segment.page_index + 1) if last_segment else end.page_index + 1,
                is_cross_page=(
                    last_segment.page_index > start.page_index if last_segment else False
                ),
                segments=segments,
                label=row["label"],
            )
        )
    return records


# ── 边界避让插图 ─────────────────────────────────────────────────────


def _figure_like(rect: fitz.Rect) -> bool:
    """像「插图」而不是版式线条/底纹的对象。"""
    return (
        FIGURE_MIN_HEIGHT <= rect.height <= FIGURE_MAX_HEIGHT
        and rect.width <= FIGURE_MAX_WIDTH
    )


def _figure_obstacles(page: fitz.Page, recurring: set[int]) -> list[fitz.Rect]:
    """该页上够格称为图形的对象矩形：内嵌位图 + Word 画的矢量线条图。

    矢量那一路是必须的：讲义里的插图多是 Word 画出来的线条画（容器、电路、
    光路），本地内嵌位图抽取一张也拿不到，但它们的线条会结结实实落进题卡 ——
    实测第 27 题卡图右下角那四条短桩，就是后一题两个容器的四道侧壁（每条
    0.05pt 宽、60pt 高，按"位图"口径根本看不见）。
    """
    rects: list[fitz.Rect] = []
    for info in page.get_image_info(xrefs=True):
        # 跨页复现的是页眉/水印/logo，不是插图；拿它当障碍会让整页边界乱动。
        if info.get("xref") in recurring:
            continue
        rect = fitz.Rect(info["bbox"])
        if _figure_like(rect):
            rects.append(rect)
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        if _figure_like(rect):
            rects.append(rect)
    return rects


# ── 小问泄漏修复 ─────────────────────────────────────────────────────

# 题区间首行是「(2) …」「（3）…」这类小问标记。只认 k>=2：(1) 例外 ——
# 它可能真是本题的第一小问，动了反而把人家的题头拆走。
_SUBQUESTION_RE = re.compile(r"^[\(（]\s*(\d{1,2})\s*[\)）]")


def repair_subquestion_leak(
    line_index: dict[int, TextLine],
    questions: list[dict],
    warnings: list[str],
) -> int:
    """把误划进本题区间的**上一题小问**行还回去，返回修复的题数。

    实测（MinerU 通道和平卷）：第 21 题的（2）被划进第 22 题区间，于是
    第 22 题的题干开头是上一题的半截小问、题卡图里也有 —— boundary_audit
    的 first_line_unnumbered 只能把它标成 needs_review，**内容还是错的**，
    用户得手动删。这里在构建 spans / records 之前确定性修掉，下游裁卡、
    结构化、答案归一拿到的就都是对的区间。

    三条判据同时满足才动（宁缺勿滥）：
    1. 本题区间首行是「(k)」小问且 k >= 2；
    2. 上一题区间里出现过「(1)」—— 说明上一题本就有小问序列，这些行是它的延续；
    3. 本题区间内能找到本题主编号行（如「22．」）—— 修复后本题仍有题头。

    修复方式：本题 start_line 前移到主编号行，上一题 end_line 扩到该行前一行。
    相邻区间原本不重叠，所以这两处改动正好把泄漏行整体划回上一题。
    """
    repaired = 0
    for index in range(1, len(questions)):
        cur = questions[index]
        prev = questions[index - 1]
        first = line_index.get(cur["start_line"])
        if first is None:
            continue
        match = _SUBQUESTION_RE.match(first.text.strip())
        if match is None or int(match.group(1)) < 2:
            continue
        number = _label_number(cur.get("label"))
        if number is None:
            continue

        prev_texts = [
            line_index[lid].text
            for lid in range(prev["start_line"], prev["end_line"] + 1)
            if lid in line_index
        ]
        if not any("(1)" in text or "（1）" in text for text in prev_texts):
            continue

        # 本题主编号行：区间里第一个「22．」形状的行。找不到就说明本题
        # 整段都没有题头，动不了 —— 交给 boundary_audit 照常报警。
        main_re = re.compile(rf"^\D{{0,4}}?{number}\s*[．.、]")
        main_line = next(
            (
                lid
                for lid in range(cur["start_line"], cur["end_line"] + 1)
                if lid in line_index and main_re.match(line_index[lid].text.strip())
            ),
            None,
        )
        if main_line is None or main_line <= cur["start_line"]:
            continue

        leaked = main_line - cur["start_line"]
        prev["end_line"] = main_line - 1
        cur["start_line"] = main_line
        repaired += 1
        warnings.append(
            f"第 {number} 题区间开头混入了上一题的小问（{leaked} 行，"
            f"如 {first.text.strip()[:24]!r}），已还给第 "
            f"{_label_number(prev.get('label')) or '?'} 题。"
        )
    return repaired


def avoid_figure_cuts(
    doc: fitz.Document,
    records: list[QuestionRecord],
    lines_by_page: dict[int, list[TextLine]],
    warnings: list[str],
    *,
    max_shift: float = FIGURE_SNAP_MAX_SHIFT,
) -> int:
    """把切穿插图的题底边界上移到插图顶部（原地改写 records，返回改了几处）。

    为什么需要：讲义是双栏排版，右栏的插图可以横跨左栏题号所在的水平线，而
    「上一题底边界 = 下一题首行 y0 - GAP」这条规则只看文字行，看不到图，于是
    把下一题插图的顶部切一截留在上一题的题卡里。实测某讲义 75 题里 4 处这样的
    切穿：第 27 题的【答案】C 早已结束，题卡右下角却多出四条容器壁短桩。

    三条自限，防止"避让"本身制造新错误：

    - **只上移，不下移。** 下移会把下一题的题号行吞进上一题题卡，那比"卡图多
      一角"严重得多：卡图缺角有插图资产兜着（插图按自己的矩形裁，完整无损），
      题号被吞则是正文错位，用户只能自己发现。
    - **上移后底边界必须仍在本题末行之下**（留 TOP_PADDING）。宁可留着那一角
      杂质，也绝不裁掉本题的文字 —— 这是本次改动里唯一不可退让的底线。
    - **只避让"大部分落在边界之下"的图**：那说明图属于下方（下一题或下一个
      板块），上方只是被切进来的一角。反过来，大部分在边界之上的图属于本题卡
      自己 —— 这与插图归属的「交集面积最大者胜出」是同一口径。对这类图把边界
      上移，等于把本题自己的插图整个推出卡外，比"缺一角"更糟（实测第 40 题：
      图 32.2pt 在界内、18.1pt 在界外，就该原样不动）。
    - **位移不超过 max_shift。**

    返回值为改动处数，供调用方记日志。
    """
    recurring = recurring_xrefs(doc)
    obstacles_cache: dict[int, list[fitz.Rect]] = {}

    def obstacles(page_index: int) -> list[fitz.Rect]:
        if page_index not in obstacles_cache:
            obstacles_cache[page_index] = _figure_obstacles(doc[page_index], recurring)
        return obstacles_cache[page_index]

    changed = 0
    for record in records:
        for segment in record.segments:
            cut = segment.y1
            # 本题末行的下沿：上移绝不能越过它。
            bottoms = [
                line.y1
                for line in lines_by_page.get(segment.page_index, [])
                if line.y0 >= segment.y0 - 1 and line.y0 <= cut
            ]
            floor = (max(bottoms) if bottoms else segment.y0) + TOP_PADDING

            lower_majority = [
                rect
                for rect in obstacles(segment.page_index)
                if rect.y0 < cut - FIGURE_STRADDLE_TOL
                and rect.y1 > cut + FIGURE_STRADDLE_TOL
                # 大部分在边界之下 —— 图属于下方，界内那一角才是多出来的。
                and (rect.y1 - cut) > (cut - rect.y0)
            ]
            if not lower_majority:
                continue
            # 只上移，所以位移最小的就是"顶边离边界最近"的那张。
            edge = max(rect.y0 for rect in lower_majority)
            # 余量不足就退回贴边：宁可留一像素细点，也不越过本题末行。
            target = edge - FIGURE_CLEARANCE if edge - FIGURE_CLEARANCE >= floor else edge
            if target < floor or cut - target > max_shift:
                continue

            segment.y1 = target
            changed += 1
            warnings.append(
                f"插图避让：第 {record.number} 题的题卡底边界上移 {cut - target:.1f}pt"
                f"（y={cut:.1f} → {target:.1f}），让开一张横跨该边界、"
                f"大部分位于边界下方的插图（该图不属于本题）。"
            )

    return changed


# ── 对外主流程 ───────────────────────────────────────────────────────


def _as_question_payload(payload) -> dict | None:
    """模型偶尔把 questions 数组直接吐出来，外面不包对象。

    只对「每个元素都是带行区间的对象」的数组宽容——否则会把乱七八糟的
    非对象响应当成题目，那比直接报错更难查。
    """
    if not isinstance(payload, list) or not payload:
        return None
    if not all(isinstance(row, dict) for row in payload):
        return None
    if not all("start_line" in row or "end_line" in row for row in payload):
        return None
    return {"questions": payload}


async def _request_boundary_batch(
    config: dict,
    user_text: str,
    first_page: int,
    last_page: int,
    result: BoundaryResult,
    retries: int = 2,
    system: str = BOUNDARY_SYSTEM,
):
    """单批边界判定：裸数组容错 + 失败重试。

    一个批次挂掉会让整份文档（实测 38 页要 9 分钟）全部报废，所以这里
    自己重试，而不是把 VLMError 直接抛给调用方。

    system 由调用方按学科渲染（见 boundary_system_prompt），默认退回基线，
    保证未显式传学科时行为与历史逐字一致。
    """
    span = f"第 {first_page + 1}-{last_page + 1} 页"
    for attempt in range(retries + 1):
        payload = await call_vlm_json(config, system=system, user_text=user_text)
        if not isinstance(payload, dict):
            repaired = _as_question_payload(payload)
            if repaired is not None:
                result.warnings.append(f"{span}批次：模型返回裸数组，已按 questions 解析")
                return repaired
            if attempt < retries:
                result.warnings.append(
                    f"{span}批次第 {attempt + 1} 次返回非对象，重试（{str(payload)[:80]}）"
                )
                continue
            raise VLMError(f"{span}边界判定连续 {retries + 1} 次返回非对象: {str(payload)[:200]}")
        return payload
    raise VLMError(f"{span}边界判定未拿到有效响应")


def _label_number(label: str | None) -> int | None:
    """取 label 里的题号：「22．」→ 22、「（多选）11．」→ 11、「【例1】」→ 1。"""
    match = re.search(r"\d+", label or "")
    return int(match.group(0)) if match else None


def _line_leading_number(text: str) -> int | None:
    match = LEADING_NUMBER_RE.match(text.strip())
    return int(match.group(1)) if match else None


def align_starts_to_number_anchors(
    questions: list[dict],
    line_index: dict[int, TextLine],
    warnings: list[str],
    *,
    max_shift: int = ANCHOR_MAX_SHIFT,
) -> list[dict]:
    """把起点晚于题号行的题区间前移到题号行（确定性、零模型成本）。

    实测动机：和平卷第 22 题，LLM 把题干首行「22．（6 分）…都闭合」划进了
    第 21 题，于是第 22 题题干从半句话开始，直到用户对着截图才发现。
    LLM 的划界是概率性的，但**题号是 PDF 里客观存在的文本**——拿它当锚点
    做确定性校正，比再问一次模型更可靠也更便宜。

    三条自限，防止校正本身制造新错误：
    - 只在题号全卷唯一时生效。讲义的【例1】会在多个板块重复出现，锚点不唯一，
      强行校正会把不同板块的题搅在一起（返回原样）。
    - 只前移不后移，且位移不超过 max_shift 行。跨度更大说明模型判的是另一道题。
    - 前移后上一题的 end_line 相应回退；若回退到小于它自己的起点，则放弃这次校正。
    """
    numbers = [_label_number(row.get("label")) for row in questions]
    usable = [n for n in numbers if n is not None]
    # 题号不唯一（讲义形态）或大半个卷子没有题号 → 不做。
    if len(usable) < max(2, len(questions) // 2) or len(set(usable)) != len(usable):
        return questions

    for index, row in enumerate(questions):
        number = numbers[index]
        if number is None:
            continue
        start = int(row["start_line"])
        current = line_index.get(start)
        if current is None:
            continue
        # 倒序找最近的一行：锚点越靠近当前起点越可信。
        anchor = None
        for line_id in range(start - 1, max(-1, start - 1 - max_shift), -1):
            line = line_index.get(line_id)
            if line is None or line.page_index != current.page_index:
                continue
            if _line_leading_number(line.text) == number:
                anchor = line_id
                break
        if anchor is None:
            continue

        previous = questions[index - 1] if index > 0 else None
        if previous is not None:
            new_end = anchor - 1
            if new_end < int(previous["start_line"]):
                continue
            previous["end_line"] = new_end
        row["start_line"] = anchor
        warnings.append(
            f"题号锚点校正：第 {number} 题起点从 line {start} 前移到 line {anchor}"
            f"（该行原文以题号开头）"
        )
    return questions


async def detect_boundaries(
    config: dict,
    doc: fitz.Document,
    lines: list[TextLine],
    *,
    subject: str | None = None,
    doc_kind_hint: str | None = None,
    question_page_count: int | None = None,
    cancel_check=None,
) -> BoundaryResult:
    """分批调用视觉模型判定题目边界，归并成全局 QuestionRecord 列表。

    Args:
        config: get_vision_config 预先读出的视觉模型配置。
        doc: 已打开的 PDF，用于计算页面几何。
        lines: build_line_inventory 的产出。
        subject: 学科，影响 prompt 里的公式严格度。
        doc_kind_hint: 上传时人工指定的文档形态（paper / handout），作为提示。
        question_page_count: 题目页数。非空时，起始行落在该页之后的题目视为
            答案/解析区的重印，直接剔除（区域本身仍留给答案归一取用）。
        cancel_check: 异步可调用，返回 True 表示用户已取消。
    """
    result = BoundaryResult(doc_kind=doc_kind_hint or "paper")
    if not lines:
        result.warnings.append("行清单为空，无法判定题目边界。")
        return result

    line_index = {line.line_id: line for line in lines}
    lines_by_page = _page_lines(lines)
    page_count = max(line.page_index for line in lines) + 1
    batches = plan_batches(lines)
    owned = _owned_ranges(batches, lines)
    # 按学科渲染边界 system prompt：仅英语追加篇章题拆分/防漏规则，他科逐字不变。
    boundary_system = boundary_system_prompt(subject)

    reports: list[tuple[tuple[int, int], list[dict], list[dict]]] = []
    kinds: list[str] = []

    batch_semaphore = asyncio.Semaphore(BOUNDARY_CONCURRENCY)

    async def _one_batch(index, first_page, last_page, owned_range):
        """跑一批。批次之间互不依赖（归并靠 owned_range 而非顺序），串行只是遗漏。"""
        async with batch_semaphore:
            if cancel_check and await cancel_check():
                raise ExtractCancelled()
            payload = await _request_boundary_batch(
                config,
                boundary_user_text(
                    to_prompt_text(_batch_line_ids(lines, first_page, last_page)),
                    total_lines=len(lines),
                    page_count=page_count,
                    doc_kind_hint=doc_kind_hint,
                    subject=subject,
                ),
                first_page,
                last_page,
                result,
                system=boundary_system,
            )
        return index, first_page, last_page, owned_range, payload

    # gather 保序：reports 的顺序与串行时逐字一致，归并结果不变
    batch_results = await asyncio.gather(
        *[
            _one_batch(index, first_page, last_page, owned_range)
            for index, ((first_page, last_page), owned_range) in enumerate(zip(batches, owned))
        ]
    )

    for index, first_page, last_page, owned_range, payload in batch_results:
        kinds.append(str(payload.get("doc_kind") or "").strip())
        questions, dropped = _parse_questions(payload, line_index)
        # 越界/非法条目必须可见：它们直接对应丢失的内容。
        result.warnings.extend(
            f"第 {first_page + 1}-{last_page + 1} 页批次：{item}" for item in dropped
        )
        reports.append((owned_range, questions, _parse_regions(payload, line_index)))
        logger.info(
            "boundary batch %s/%s (p%s-p%s): %s questions, %s regions",
            index + 1, len(batches), first_page + 1, last_page + 1,
            len(questions), len(reports[-1][2]),
        )

    questions, regions = _merge_reports(reports, len(lines), result.warnings)

    # 答案/解析区会把正文题目整题重印一遍并附上答案。这些重印题若当独立题目
    # 入库就是重复题，必须剔除；但该区域的行要留给 answers.py 作第二答案源，
    # 所以只过滤 questions、不动 regions（regions 里的 answer_key 全靠它）。
    answer_area_line_ids: set[int] = set()
    if question_page_count is not None:
        # 整段答案区都算答案源，不依赖模型把它判成 answer_key —— 实测模型会把
        # 答案区的重印题干判成 question、把解析文字判成 other，一个 answer_key
        # 都不给，结果正文题全部拿不到答案。
        answer_area_line_ids = {
            line.line_id for line in lines if line.page_index >= question_page_count
        }

        def _starts_in_answer_area(row: dict) -> bool:
            line = line_index.get(row["start_line"])
            return line is not None and line.page_index >= question_page_count

        reprinted = [row for row in questions if _starts_in_answer_area(row)]
        if reprinted:
            questions = [row for row in questions if not _starts_in_answer_area(row)]
            result.warnings.append(
                f"答案/解析区（第 {question_page_count + 1} 页起）里的 {len(reprinted)} 道题"
                f"是正文重印，已剔除；该区域 {len(answer_area_line_ids)} 行强制作为"
                f"答案来源参与归一。"
            )

    _report_uncovered(line_index, questions, regions, result.warnings)

    questions = align_starts_to_number_anchors(questions, line_index, result.warnings)

    # 小问泄漏修复：上一题的小问被划进本题区间时，把那几行还给上一题。
    # 必须放在 spans / records 构建**之前** —— 下游裁卡、结构化、答案归一
    # 全以这里的行区间为准；只报警不修复，用户拿到的题干仍是错的。
    # 两条通道（大模型 / MinerU）都在这里汇合，一处生效、两条通道同修。
    repaired = repair_subquestion_leak(line_index, questions, result.warnings)
    if repaired:
        logger.info("boundary：小问泄漏修复了 %d 处", repaired)

    result.doc_kind = _doc_kind([kind for kind in kinds if kind], doc_kind_hint)
    result.spans = [
        QuestionSpan(qid=order, **row) for order, row in enumerate(questions, start=1)
    ]
    result.regions = [NonQuestionRegion(**row) for row in regions]
    result.excluded_line_ids = {
        line_id for row in regions for line_id in range(row["start_line"], row["end_line"] + 1)
    }
    # 被剔除的重印题若不排除出分母，覆盖率会被答案区拖垮。
    result.excluded_line_ids |= answer_area_line_ids
    result.answer_key_line_ids = {
        line_id
        for row in regions
        if row["kind"] == "answer_key"
        for line_id in range(row["start_line"], row["end_line"] + 1)
    }
    # 答案区整段兜底成答案源：模型没判出 answer_key 时这里是唯一救命稻草。
    result.answer_key_line_ids |= answer_area_line_ids
    result.records = _build_records(
        doc,
        line_index,
        lines_by_page,
        questions,
        regions,
        question_page_count=question_page_count,
    )

    # 边界避让插图。必须放在调用方的 boundary_audit **之前**：让形状校验
    # 看到的也是避让后的边界，否则"校验通过、实际裁图不同"会白白多一层疑点。
    # 两条通道（大模型 / MinerU）都在这里汇合，所以一处生效、两条通道同修。
    adjusted = avoid_figure_cuts(doc, result.records, lines_by_page, result.warnings)
    if adjusted:
        logger.info("boundary：插图避让调整了 %d 处题底边界", adjusted)

    empty = [record.number for record in result.records if not record.segments]
    if empty:
        result.warnings.append(f"以下题目算不出可裁剪片段：{empty}")
    return result
