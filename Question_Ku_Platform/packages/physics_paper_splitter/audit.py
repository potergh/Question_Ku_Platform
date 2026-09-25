"""覆盖率审计 —— 判断「原文有多少内容真的进了题卡」。

现有 CompletenessValidator 只查题号连续性、题卡非空与贴边截断，无法发现
「12 页内容不属于任何题卡」这类静默丢失。本模块补上这一维度，并作为
新识别通道的入库闸门：审计不通过时禁止静默入库。

同样适用于旧几何通道，可用于给历史数据补审计。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .lines import TextLine
from .models import QuestionRecord

# 行的 y 落在片段 [y0 - TOL, y1 + TOL] 内即视为被该题卡覆盖。
TOLERANCE_PT = 6.0

# 丢失行的留样上限：够人工判断「该不该管」即可，不必全量落盘。
LOST_SAMPLE_LIMIT = 20
LOST_SAMPLE_CHARS = 60

# 覆盖率低于此值 → 阻断入库。
COVERAGE_FLOOR = 0.95
# 答案匹配率低于此值 → 阻断入库。
ANSWER_FLOOR = 0.8

# 题号在行首且后跟分隔符（14．/ 14、/ 14.；【例1】/（多选）11．也在容差内）。
# 与 api_extract/answers.py 的 LEADING_NUMBER_RE 同一形状：前缀最多 4 个非数字字符。
# 分隔符必须含 】）)：讲义的「【例1】」与「（1）」是标准题号写法，漏掉它们会让
# 「首行就是题号」被判成「首行不是题号」——暑期卷讲义实测 57 处误报全部源于此。
LEADING_NUMBER_RE = re.compile(r"^\D{0,4}?(\d{1,3})\s*[．.、】）)]")


@dataclass(slots=True)
class BoundaryFinding:
    """确定性边界校验的一条发现。

    kind 取值：
    - span_overlap           相邻两题的行区间重叠（prompt 明令禁止，出现即违约）
    - number_sequence_broken 全卷唯一编号时，题号未按 start_line 递增
    - first_line_unnumbered  题区间首行没有本题主编号（题头被切掉或标错区间）
    - coverage_gap           题区间内的行没有落进本题卡任何片段（裁图缺内容）
    """

    qid: int
    number: int
    kind: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CoverageReport:
    """整份文档的覆盖审计结果。"""

    total_lines: int = 0
    covered_lines: int = 0
    coverage_ratio: float = 1.0
    total_chars: int = 0
    lost_chars: int = 0
    # 丢失的行（page / text），只留前若干条。
    # 只报「丢了 76 字」没法行动 —— 得知道丢的是哪几行才知道该不该管
    # （实测河东卷丢的 2 行是页脚说明，但也有可能是真题干）。
    lost_samples: list[dict] = field(default_factory=list)
    # 被显式归类为非题目区域（卷首信息、章节标题、答案区等）的行，不计入分母。
    excluded_lines: int = 0
    excluded_chars: int = 0
    orphan_pages: list[int] = field(default_factory=list)  # 1-based，有内容却没有题卡的页
    answer_total: int = 0
    answer_matched: int = 0
    answer_match_ratio: float | None = None
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _segments_by_page(records: list[QuestionRecord]) -> dict[int, list[tuple[float, float]]]:
    covered: dict[int, list[tuple[float, float]]] = {}
    for record in records:
        for segment in record.segments:
            covered.setdefault(segment.page_index, []).append((segment.y0, segment.y1))
    return covered


def coverage_audit(
    lines: list[TextLine],
    records: list[QuestionRecord],
    page_count: int,
    *,
    excluded_line_ids: set[int] | None = None,
    no_text_pages: set[int] | None = None,
    answer_total: int = 0,
    answer_matched: int = 0,
    answer_applicable: bool = True,
    coverage_floor: float = COVERAGE_FLOOR,
    answer_floor: float = ANSWER_FLOOR,
) -> CoverageReport:
    """统计行清单被题卡覆盖的比例，并给出是否阻断入库的结论。

    审计原则：每一行要么属于某道题，要么被调用方显式归类为非题目区域
    （excluded_line_ids）；两者都不属于的行计入丢失。没有这个显式机制时，
    卷首信息、章节标题等本就不属于题卡的内容会拖低覆盖率。

    Args:
        lines: 行清单（extract_line_inventory 的输出）。
        records: 题卡记录（含 segments）。
        page_count: 参与审计的总页数。
        excluded_line_ids: 非题目区域的 line_id 集合（0-based 页索引无关）。
        no_text_pages: 没有文字层的纯图页（0-based）；未被题卡覆盖时计入孤儿页。
        answer_total: 应有答案的题目数。
        answer_matched: 已匹配到答案的题目数。
        answer_applicable: 是否存在答案源（行内【答案】/文末答案区/配对答案文档）。
            为 False 时不做答案匹配断言 —— 纯题目卷本来就不带答案，而
            answer_total 恒等于题数，一律断言会让这类文档 100% 被闸门阻断、
            永远无法入库。数字照常记录，由调用方另行提示。
    """
    report = CoverageReport()
    covered = _segments_by_page(records)
    excluded = excluded_line_ids or set()

    pages_with_content: set[int] = set()
    for line in lines:
        if not line.text:
            continue
        if line.line_id in excluded:
            report.excluded_lines += 1
            report.excluded_chars += len(line.text)
            continue
        pages_with_content.add(line.page_index)
        report.total_lines += 1
        report.total_chars += len(line.text)
        spans = covered.get(line.page_index, [])
        if any(y0 - TOLERANCE_PT <= line.y0 <= y1 + TOLERANCE_PT for y0, y1 in spans):
            report.covered_lines += 1
        else:
            report.lost_chars += len(line.text)
            if len(report.lost_samples) < LOST_SAMPLE_LIMIT:
                report.lost_samples.append(
                    {
                        "page": line.page_index + 1,
                        "line_id": line.line_id,
                        "text": line.text.strip()[:LOST_SAMPLE_CHARS],
                    }
                )

    if report.total_lines:
        report.coverage_ratio = round(report.covered_lines / report.total_lines, 4)

    # 孤儿页：有正文却没被任何题卡覆盖；纯图页（如扫描插图页）同样计入。
    image_pages = no_text_pages or set()
    report.orphan_pages = sorted(
        page + 1
        for page in range(page_count)
        if page not in covered and (page in pages_with_content or page in image_pages)
    )

    if answer_total:
        report.answer_total = answer_total
        report.answer_matched = answer_matched
        if answer_applicable:
            report.answer_match_ratio = round(answer_matched / answer_total, 4)
            if report.answer_match_ratio < answer_floor:
                report.blocked = True
                report.reasons.append(
                    f"答案匹配率 {report.answer_match_ratio:.1%} 低于阈值 {answer_floor:.0%}"
                    f"（{answer_matched}/{answer_total}）。"
                )

    if report.coverage_ratio < coverage_floor:
        report.blocked = True
        detail = ""
        if report.lost_samples:
            first = report.lost_samples[0]
            detail = f"（例如第 {first['page']} 页：{first['text'][:40]!r}）"
        report.reasons.append(
            f"内容覆盖率 {report.coverage_ratio:.1%} 低于阈值 {coverage_floor:.0%}，"
            f"有 {report.lost_chars} 字未进入任何题卡{detail}。"
        )

    if report.orphan_pages:
        report.blocked = True
        report.reasons.append(f"以下页面完全没有题卡：{report.orphan_pages}。")

    if not records:
        report.blocked = True
        report.reasons.append("没有切出任何题目。")

    return report


def item_flags(
    record: QuestionRecord,
    *,
    has_answer: bool,
    has_formula: bool = False,
    figure_count: int = 0,
) -> list[str]:
    """单题级别的审计标记，写入 ExtractItemData.audit_flags。"""
    flags: list[str] = []
    if not has_answer:
        flags.append("no_answer")
    if record.is_cross_page:
        flags.append("cross_page")
    if record.height_px > 9000:
        flags.append("tall_card")
    if has_formula:
        flags.append("has_formula")
    if figure_count:
        flags.append(f"figures:{figure_count}")
    if not record.segments:
        flags.append("no_segments")
    return flags


def boundary_audit(
    lines: list[TextLine],
    records: list[QuestionRecord],
    spans: Sequence,
    *,
    excluded_line_ids: set[int] | None = None,
    tolerance_pt: float = TOLERANCE_PT,
    doc_kind: str | None = None,
) -> list[BoundaryFinding]:
    """对边界判定的产出做确定性校验（零模型成本，结果可复算）。

    覆盖率审计（coverage_audit）是全卷总账，丢 200 字摊在 26 题上报表照样
    全绿；本函数把同样的几何事实下沉到单题粒度，专抓三类系统性错误：
    1. LLM 输出的行区间互相重叠或题号乱序 —— prompt 契约的硬违约；
    2. 题区间首行不像本题题号 —— 题头被切掉（实测第 22 题题干首行
       「22．（6 分）…都闭合」被模型划进上一题，首行从半句话开始）；
    3. 题区间内的行没有落进本题卡片段 —— 区间说有、裁图没给，题干文本与
       题卡图互相矛盾。

    **讲义形态（doc_kind="handout"）只跑第 1 条**。实测暑期卷讲义 75 题报
    73 处，逐条看下来几乎全是误报：题号在板块内重启（【例1】出现十几次）、
    章节标题（「二、液体压强」）夹在题目之间被当成缺题号的题、双栏排版让
    行 y 与题卡片段的对应关系失真。继续报下去等于狼来了，真实的 needs_review
    会被淹没。讲义的内容完整性由全卷覆盖率（coverage_audit）兜底。

    Args:
        lines: 全量行清单（extract_line_inventory 的产出）。
        records: 题卡记录，与 spans 按下标一一对应。
        spans: 边界判定的行区间（duck-typed：需有 qid/label/start_line/end_line）。
        excluded_line_ids: 显式非题目区域的 line_id（不参与首行/覆盖判定）。
        tolerance_pt: 行 y 判定落入片段的容差，与 coverage_audit 同一口径。
        doc_kind: 文档形态；"handout" 时只保留与形态无关的区间重叠检查。

    Returns:
        发现列表（可能为空）。发现只升级告警与 needs_review，不直接阻断入库。
    """
    excluded = excluded_line_ids or set()
    line_by_id = {line.line_id: line for line in lines}
    findings: list[BoundaryFinding] = []
    if not records or not spans:
        return findings
    if len(records) != len(spans):
        return [
            BoundaryFinding(
                qid=0,
                number=0,
                kind="span_record_mismatch",
                detail=f"边界校验无法执行：records ({len(records)}) 与 spans "
                f"({len(spans)}) 数量不一致",
            )
        ]

    ordered = sorted(
        zip(spans, records), key=lambda pair: pair[0].start_line
    )

    # ① 区间重叠：任何相邻两题共享 line_id 都是违约。
    for (prev_span, _prev_record), (next_span, _next_record) in zip(ordered, ordered[1:]):
        if next_span.start_line <= prev_span.end_line:
            findings.append(
                BoundaryFinding(
                    qid=next_span.qid,
                    number=_record_number(next_span, prev_span),
                    kind="span_overlap",
                    detail=(
                        f"第 {prev_span.label or prev_span.qid} 题与第 "
                        f"{next_span.label or next_span.qid} 题的行区间重叠"
                        f"（{prev_span.end_line} >= {next_span.start_line}）"
                    ),
                )
            )

    # ② 题号单调：仅当全卷编号唯一（试卷形态）时可靠；讲义板块重启天然乱序。
    labels_numbers = [_label_number(span.label) for span, _record in ordered]
    if None not in labels_numbers and len(set(labels_numbers)) == len(labels_numbers):
        for index in range(1, len(labels_numbers)):
            if labels_numbers[index] < labels_numbers[index - 1]:
                span, _record = ordered[index]
                findings.append(
                    BoundaryFinding(
                        qid=span.qid,
                        number=labels_numbers[index],
                        kind="number_sequence_broken",
                        detail=(
                            f"第 {labels_numbers[index]} 题出现在第 "
                            f"{labels_numbers[index - 1]} 题之前（按行序）"
                        ),
                    )
                )

    # 讲义形态不做单题级判定（理由见 docstring），只保留区间重叠检查。
    if (doc_kind or "paper") == "handout":
        return findings

    for span, record in zip(spans, records):
        number = _label_number(span.label) or span.qid

        # ③ 首行题号：题区间第一行应含本题主编号，否则题头多半被切。
        first_line = next(
            (
                line
                for line_id in range(span.start_line, span.end_line + 1)
                if line_id not in excluded
                and (line := line_by_id.get(line_id))
                and line.text.strip()
            ),
            None,
        )
        if first_line is not None:
            match = LEADING_NUMBER_RE.match(first_line.text.strip())
            expected = _label_number(span.label)
            if match is None or (expected is not None and int(match.group(1)) != expected):
                findings.append(
                    BoundaryFinding(
                        qid=span.qid,
                        number=number,
                        kind="first_line_unnumbered",
                        detail=(
                            f"第 {number} 题区间首行不是本题主编号"
                            f"（首行：{first_line.text.strip()[:30]!r}）"
                        ),
                    )
                )

        # ④ 分题覆盖：题区间内的行必须落进本题卡片段，否则文本与裁图矛盾。
        segments_by_page: dict[int, list[tuple[float, float]]] = {}
        for segment in record.segments:
            segments_by_page.setdefault(segment.page_index, []).append(
                (segment.y0, segment.y1)
            )
        missed: list[TextLine] = []
        for line_id in range(span.start_line, span.end_line + 1):
            line = line_by_id.get(line_id)
            if line is None or not line.text.strip():
                continue
            spans_on_page = segments_by_page.get(line.page_index, [])
            if not any(
                y0 - tolerance_pt <= line.y0 <= y1 + tolerance_pt
                for y0, y1 in spans_on_page
            ):
                missed.append(line)
        if missed:
            findings.append(
                BoundaryFinding(
                    qid=span.qid,
                    number=number,
                    kind="coverage_gap",
                    detail=(
                        f"第 {number} 题有 {len(missed)} 行区间内文字没有落进本题卡"
                        f"（如 {missed[0].text.strip()[:24]!r}）"
                    ),
                )
            )

    return findings


def _label_number(label: str | None) -> int | None:
    """从 label 原文取整数题号：'1．'/'【例1】'/'（多选）11．' 都取其中的数字。"""
    match = re.search(r"\d{1,3}", label or "")
    return int(match.group(0)) if match else None


def _record_number(span, fallback) -> int:
    return _label_number(span.label) or _label_number(fallback.label) or span.qid
