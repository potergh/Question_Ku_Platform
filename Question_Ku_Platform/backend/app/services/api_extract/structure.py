"""逐题结构化：题卡文字（+ 必要时题卡图）-> 结构化 JSON。

成本优化：只有题卡含插图、或文字层里出现公式迹象时才把题卡图发给模型，
纯文本题只发行清单文本。实测讲义里大量题目是纯文字，这一条能砍掉大头开销。

容错：单题失败不阻塞整批 —— 标记 needs_review 并记下错误，用户在预览页
能看到「哪几题没识别出来」，而不是整份文档白跑。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from physics_paper_splitter.lines import TextLine, lines_in_range, to_prompt_text

from . import ExtractCancelled
from .boundary import BoundaryResult
from .prompts import structure_system_prompt, structure_user_text
from .vlm_client import VLMError, call_vlm_json

logger = logging.getLogger(__name__)

# 并发上限：DashScope 对单账号有 QPS 限制，超过会批量 429。
# 并发上限。实测单题一次调用约 30s（端点 41 tok/s），25 题在 3 并发下要等 9 轮
# ≈4.5 分钟。提到 6 后约 4.5 轮；触发 429 有退避重试兜底，取不到配额时最坏退化回串行。
DEFAULT_CONCURRENCY = 6

# 文字层里出现这些迹象时，把题卡图一并发给模型校正。
FORMULA_HINT_RE = re.compile(
    r"[²³⁴√∑∫∮≤≥±×÷≠≈∝∈⊥∥△∠θρμλσΩ°℃Å]|"
    r"\\frac|\\sqrt|\^\{|_\{|"
    r"[A-Za-z]\s*[=＝]\s*\d|"
    r"\d\s*/\s*\d"
)
# 文字层里已经出现替换字符，说明公式/特殊字形抽不出来，必须看图。
REPLACEMENT_CHAR = "\ufffd"

FIGURE_PLACEHOLDER_RE = re.compile(r"\[\[\s*FIGURE[_\- ]?(\d*)\s*\]\]", re.IGNORECASE)


@dataclass(slots=True)
class StructuredItem:
    """一道题的结构化结果。qid 与 BoundaryResult.spans / records 对齐。"""

    qid: int
    label: str = ""
    section: str | None = None
    stem_md: str = ""
    options: list[dict] = field(default_factory=list)
    # 英语篇章题（完形/阅读等）的小题列表：{label,stem,options,answer}。
    # stem_md 存共享材料；非篇章题为空列表。
    sub_questions: list[dict] = field(default_factory=list)
    qtype: str | None = None
    score: float | None = None
    has_formula: bool = False
    figure_placeholders: list[str] = field(default_factory=list)
    answer_inline: str | None = None
    explanation_inline: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    needs_review: bool = True
    # 是否把题卡图发给了模型（成本与可复现性审计用）。
    used_image: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def needs_card_image(span_text: str, figure_paths: list[str]) -> bool:
    """判断这道题是否值得付图片的 Token 成本。"""
    if figure_paths:
        return True
    if REPLACEMENT_CHAR in span_text:
        return True
    return bool(FORMULA_HINT_RE.search(span_text))


def _clean_options(rows) -> list[dict]:
    """模型偶尔把 options 返回成 {"A": "..."} 字典，统一成 [{label, content}]。"""
    if isinstance(rows, dict):
        return [{"label": str(k).strip(), "content": str(v or "").strip()} for k, v in sorted(rows.items())]
    if not isinstance(rows, list):
        return []
    cleaned: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            label = str(row.get("label") or "").strip()
            content = str(row.get("content") or "").strip()
            if label or content:
                cleaned.append({"label": label, "content": content})
        elif isinstance(row, str) and row.strip():
            # "A. xxx" 形态的兜底拆分
            match = re.match(r"^\s*([A-Da-d])\s*[．\.、:：]\s*(.*)$", row)
            if match:
                cleaned.append({"label": match.group(1).upper(), "content": match.group(2).strip()})
            else:
                cleaned.append({"label": "", "content": row.strip()})
    return cleaned


def _clean_sub_questions(rows) -> list[dict]:
    """把模型返回的篇章题小题数组归一为 [{label,stem,options,answer}]。

    非法项静默降级（与非篇章题返回空列表），绝不抛错。options 复用 _clean_options。
    """
    if not isinstance(rows, list):
        return []
    cleaned: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        stem = str(row.get("stem") or row.get("stem_md") or "").strip()
        answer = row.get("answer")
        answer = str(answer).strip() if answer and str(answer).strip().lower() not in ("null", "none") else ""
        explanation = row.get("explanation")
        explanation = str(explanation).strip() if explanation else ""
        options = _clean_options(row.get("options"))
        # 一道小题至少要有题干或选项才值得保留。
        if not (label or stem or options):
            continue
        sub = {"label": label, "stem": stem, "options": options}
        if answer:
            sub["answer"] = answer
        if explanation:
            sub["explanation"] = explanation
        cleaned.append(sub)
    return cleaned


def options_are_figures(options: list[dict], figure_paths: list[str]) -> bool:
    """这套选项是不是「每个选项本身就是一张图」。

    实测（2026 河东区一模 题5）：卷面上的「图3」是四个电路图并排、每个图下方标着
    A/B/C/D。切题把这**一张图切成了 4 张插图**，那四个字母被当成选项标签 —— 于是
    出现了「有标签、内容为空」的选项。只有这种形态才该按顺序把图配到选项上。

    两条同时成立才认定，宁可不做也不能把图配错位：
    选项 ≥2、每个选项都只有标签、插图数与选项数相等。

    「只有标签」包含两种写法：内容为空，**以及内容就是标签本身**。后者是模型常干的事
    （实测题5 就是 {'label': 'A', 'content': 'A'}），那同样是个没有信息的占位符，
    漏掉它这道题就还是"四张无标记的图 + 四个字母选项"，图文对不上。
    """
    if len(options) < 2 or len(figure_paths) != len(options):
        return False

    def has_no_text(option: dict) -> bool:
        label = str(option.get("label") or "").strip()
        content = str(option.get("content") or "").strip()
        return bool(label) and content in ("", label)

    return all(has_no_text(option) for option in options)


def inline_figures(
    stem_md: str,
    options: list[dict],
    figure_paths: list[str],
) -> tuple[str, list[dict], int]:
    """把插图落到该去的位置，返回 (题干, 选项, 已安置张数)。

    三条路径，按优先级：

    1. **选项就是图**（判据见 options_are_figures）：第 i 张图落到第 i 个选项。
       顺序按**选项**来，不按图在页面上的先后重排 —— A 就该配第 1 张。
       不这么做的话，图会被全部追加到题干末尾，而选项还是空的：界面上就是
       「四张没有标记的电路图 + A. B. C. D. 四个空选项」，图文对不上。
    2. 题干/选项里的 [[FIGURE_n]] 占位符按序替换。
    3. 对不上的余额追加到题干末尾（宁可多一张也不丢图）；占位符多于图时多余的
       原样删除，由调用方记 warning。
    """
    if not figure_paths:
        cleaned_stem, stem_hits = FIGURE_PLACEHOLDER_RE.subn("", stem_md or "")
        cleaned_options = []
        option_hits = 0
        for option in options:
            text, hits = FIGURE_PLACEHOLDER_RE.subn("", option.get("content", ""))
            option_hits += hits
            cleaned_options.append({**option, "content": text.strip()})
        return cleaned_stem.strip(), cleaned_options, 0

    links = [f"![figure](asset://{path})" for path in figure_paths]

    if options_are_figures(options, figure_paths):
        bound = [
            {**option, "content": links[index]}
            for index, option in enumerate(options)
        ]
        # 题干里若残留占位符，此刻已没有图可配（全给了选项），删掉而不是留个空壳。
        cleaned_stem, _hits = FIGURE_PLACEHOLDER_RE.subn("", stem_md or "")
        return cleaned_stem.strip(), bound, len(figure_paths)

    used: list[int] = []

    def _replace(match: re.Match) -> str:
        raw_index = match.group(1)
        # 模型没编号时按出现顺序取下一张。
        index = int(raw_index) - 1 if raw_index else len(used)
        if not 0 <= index < len(links) or index in used:
            index = next((i for i in range(len(links)) if i not in used), -1)
        if index < 0:
            return ""
        used.append(index)
        return links[index]

    new_stem = FIGURE_PLACEHOLDER_RE.sub(_replace, stem_md or "")
    new_options = [
        {**option, "content": FIGURE_PLACEHOLDER_RE.sub(_replace, option.get("content", ""))}
        for option in options
    ]

    leftovers = [links[i] for i in range(len(links)) if i not in used]
    if leftovers:
        new_stem = (new_stem.rstrip() + "\n\n" + "\n\n".join(leftovers)).strip()

    return new_stem.strip(), new_options, len(used)


def _parse_payload(payload, item: StructuredItem) -> None:
    """把模型返回的 JSON 填进 StructuredItem，非法值降级而不是抛错。"""
    if not isinstance(payload, dict):
        raise VLMError(f"结构化返回非对象: {str(payload)[:200]}")

    stem = payload.get("stem_md")
    item.stem_md = str(stem).strip() if stem else ""
    item.options = _clean_options(payload.get("options"))
    item.sub_questions = _clean_sub_questions(payload.get("sub_questions"))
    qtype = payload.get("type")
    item.qtype = str(qtype).strip() or None if qtype else None
    try:
        item.score = float(payload.get("score")) if payload.get("score") is not None else None
    except (TypeError, ValueError):
        item.score = None
    item.has_formula = bool(payload.get("has_formula"))
    placeholders = payload.get("figure_placeholders")
    item.figure_placeholders = (
        [str(p) for p in placeholders if str(p).strip()] if isinstance(placeholders, list) else []
    )
    answer = payload.get("answer_inline")
    item.answer_inline = str(answer).strip() or None if answer else None
    explanation = payload.get("explanation_inline")
    item.explanation_inline = str(explanation).strip() or None if explanation else None
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        item.warnings.extend(str(w) for w in warnings if str(w).strip())


# 表格正文在 content_list 里是 `<table>…` 形式的 HTML。表格被当作图片提供时，
# 这行 HTML 对模型只剩一个作用：说明"这个位置有一张表"。但它同时也是**可抄的内容** ——
# 模型照着抄一遍，界面上就会出现图片与残缺表格两份（Markdown 抄不出合并单元格）。
TABLE_HTML_PREFIX = "<table"


def _tables_covered(
    span_lines: list[TextLine], table_figures_by_qid: dict[int, int] | None, qid: int
) -> bool:
    """该题的表格 HTML 块是否**全部**拿到了渲染图。

    判据：题文里 `<table` 开头的行数 <= 该题成功落盘的表格渲染图数。
    - 没传计数（本地内嵌位图通道）或该题没有表格图 → False，退回 Markdown 规则；
    - 该题根本没有表格 HTML 行 → False（Markdown 规则对它没有影响，不该开）。
    只有"确有表格、且表格数不超过图数"才开「只认图」—— 宁可多抄一份 Markdown，
    也不能让没有图的表格整块消失。
    """
    if not table_figures_by_qid:
        return False
    have = table_figures_by_qid.get(qid, 0)
    if not have:
        return False
    needed = sum(
        1 for line in span_lines if line.text.lstrip().lower().startswith(TABLE_HTML_PREFIX)
    )
    return needed > 0 and have >= needed


def _mask_table_html(line: TextLine) -> TextLine:
    """把表格 HTML 行换成短标记；其余行原样返回。位置一概不动。

    为什么保留位置：模型要靠行位置把占位符放到正确的行上（第 4 条规则要求
    "按其在题干中出现的顺序插入到正确位置"）。所以只换文本、不动坐标。
    """
    if not line.text.lstrip().lower().startswith(TABLE_HTML_PREFIX):
        return line
    return TextLine(
        line_id=line.line_id,
        page_index=line.page_index,
        y0=line.y0,
        y1=line.y1,
        x0=line.x0,
        x1=line.x1,
        text="[表格]",
    )


# Markdown 表格的**起始**判据与前端 utils/render.js 一致：一行含 `|`，且下一行是
# 分隔行（`|---|---|`）。起始判据必须一致，否则"界面当表格渲染的"和"这里会删掉的"
# 会是两批东西，删错了用户毫无察觉。
#
# 结束位置则**刻意不同**：这里吃到空行为止，前端吃到第一行不含 `|` 的行为止。
# 原因是单元格内容里可以有换行（模型常这么写，实测第 24 题就有），按"整行含 `|`"
# 判结束会把一张表从中间截断，剩下的半边留在正文里变成乱码 —— 比不删更难看。
_TABLE_SEPARATOR = re.compile(r"^:?-+:?$")


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return len(cells) > 1 and all(_TABLE_SEPARATOR.match(cell) for cell in cells)


def strip_markdown_tables(text: str) -> tuple[str, int]:
    """删掉 Markdown 表格，返回 (新文本, 删掉的表格数)。

    用在"表格已作为图片提供"时（MinerU 通道）。此时模型会交来两份：它自己重抄的
    Markdown 表格（合并单元格必丢 —— 实测第 24 题的「方案一」分组就是这么没的），
    以及系统的整块表格图（完整）。两份都留着，用户在界面上看到的是"一张好图 +
    一张缺了行列结构的表"，所以这里删掉残缺的那份。

    为什么不能只靠 prompt：模型还会从**题卡图**里把表格再抄一遍（prompt 第 7 条
    本就鼓励"以题卡图片为准校正文字"），实测两次跑都在。所以这里做确定性兜底。
    """
    if not text:
        return text, 0
    lines = text.splitlines()
    kept: list[str] = []
    dropped = 0
    index = 0
    while index < len(lines):
        if (
            "|" in lines[index]
            and index + 1 < len(lines)
            and _is_table_separator(lines[index + 1])
        ):
            index += 2  # 表头行 + 分隔行
            # 一直吃到空行（理由见上面 _TABLE_SEPARATOR 的注释：单元格里能带换行）。
            while index < len(lines) and lines[index].strip():
                index += 1
            dropped += 1
            continue
        kept.append(lines[index])
        index += 1
    if not dropped:
        return text, 0
    # 删掉的地方会留下连续空行，折成最多一个，免得题卡里空一大片。
    compacted: list[str] = []
    for line in kept:
        if not line.strip() and compacted and not compacted[-1].strip():
            continue
        compacted.append(line)
    return "\n".join(compacted).strip(), dropped


async def structure_questions(
    config: dict,
    lines: list[TextLine],
    boundary: BoundaryResult,
    card_paths: dict[int, Path],
    figures_map: dict[int, list[str]],
    *,
    subject: str | None = None,
    table_figures_by_qid: dict[int, int] | None = None,
    cancel_check=None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[StructuredItem]:
    """对 boundary 里的每道题做结构化，返回与 spans 下标对齐的列表。

    Args:
        config: get_vision_config 预先读出的配置（并发共享 session 不安全）。
        lines: 全量行清单。
        boundary: 边界判定结果。
        card_paths: qid -> 题卡图路径（QuestionCropper 的产出）。
        figures_map: qid -> 插图相对路径列表（FigureExtractor 的产出）。
        subject: 学科，决定公式严格度。
        table_figures_by_qid: qid -> 该题拿到渲染图的表格块数（MinerU 通道）。
            某题的表格 HTML 块**全部**有图时，该题才启用「表格只认图」规则
            （禁 Markdown 重抄 + 删重抄结果）；否则该题退回 Markdown 规则。
            默认 None = 本地通道，一律 Markdown 规则。
        cancel_check: 异步可调用，返回 True 表示用户已取消。
        concurrency: 并发上限。
    """
    # 两种表格规则各备一份 system prompt，**按题选用**。原来是一个全局布尔：
    # 实测 9 张表里只要 1 张没拿到渲染图，其余 8 张有图的也被拖回 Markdown
    # 重抄，合并单元格照样丢 —— 全卷一票否决太粗了。
    prompt_figure = structure_system_prompt(subject, tables_as_figures=True)
    prompt_markdown = structure_system_prompt(subject, tables_as_figures=False)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    items: list[StructuredItem] = []

    async def run_one(span) -> StructuredItem:
        item = StructuredItem(qid=span.qid, label=span.label, section=span.section)
        span_lines = lines_in_range(lines, span.start_line, span.end_line)
        tables_have_figures = _tables_covered(span_lines, table_figures_by_qid, span.qid)
        system_prompt = prompt_figure if tables_have_figures else prompt_markdown
        if tables_have_figures:
            # 表格已作为图片提供：把它的 HTML 压成标记再给模型。raw_text 另取原始行
            # （service._raw_text），不受这里影响 —— 结构化失败时回落仍看得到原文。
            span_lines = [_mask_table_html(line) for line in span_lines]
        span_text = to_prompt_text(span_lines)
        figure_paths = figures_map.get(span.qid, [])
        card_path = card_paths.get(span.qid)

        send_image = needs_card_image(span_text, figure_paths) and card_path is not None
        item.used_image = send_image
        if not span_text.strip() and not send_image:
            item.error = "该题没有任何可用文字，也未取得题卡图"
            item.needs_review = True
            return item

        async with semaphore:
            if cancel_check and await cancel_check():
                raise ExtractCancelled()
            try:
                payload = await call_vlm_json(
                    config,
                    system=system_prompt,
                    user_text=structure_user_text(
                        span_text,
                        label=span.label,
                        section=span.section,
                        has_image=send_image,
                    ),
                    image_paths=[card_path] if send_image else None,
                )
                _parse_payload(payload, item)
            except (VLMError, asyncio.TimeoutError) as exc:
                # 单题失败不阻塞整批：留空结果 + 错误说明，预览页标红让用户补。
                item.error = str(exc)[:500]
                item.needs_review = True
                logger.warning("structure qid=%s failed: %s", span.qid, exc)
                return item

        # 表格已作为图片提供时，删掉模型重抄的那份 Markdown 表格。
        # prompt 里已经禁止重抄，但实测拦不住：模型会从**题卡图**里再抄一遍
        # （第 7 条本就鼓励"以题卡图片为准校正文字"），两次跑都在。留着两份，界面
        # 上就是"一张完整的好图 + 一张丢了合并单元格的表"，所以这里确定性兜底。
        if tables_have_figures:
            item.stem_md, stripped_tables = strip_markdown_tables(item.stem_md)
            if stripped_tables:
                item.warnings.append(
                    f"已移除模型重抄的 {stripped_tables} 处 Markdown 表格："
                    "该表格已作为完整图片提供（Markdown 表达不了合并单元格，"
                    "重抄会丢行列结构）。"
                )

        # 先判"选项是不是就是图"：替换之后选项内容就被填上了，判据不再成立。
        options_were_figures = options_are_figures(item.options, figure_paths)
        item.stem_md, item.options, replaced = inline_figures(
            item.stem_md, item.options, figure_paths
        )
        if options_were_figures:
            # 按顺序配图是启发式的：配错位（A 配上 B 的图）光看界面不容易发现，
            # 所以照样标 needs_review 让人扫一眼 —— 与"低重合只告警不过滤"同一套取舍。
            item.warnings.append(
                f"选项原文没有内容，已按顺序把 {len(figure_paths)} 张插图分配到各选项，"
                f"请核对图文是否对应"
            )
        elif figure_paths and replaced < len(figure_paths):
            item.warnings.append(
                f"题卡有 {len(figure_paths)} 张插图，模型只给出 {replaced} 个占位符，"
                f"剩余图片已追加到题干末尾"
            )
        if not item.stem_md and not item.options:
            item.error = item.error or "模型未返回任何题干内容"
        # 边界判定给的类型/分值是弱证据，结构化结果更贴近题目本身，
        # 但结构化失败时必须回落到边界值，不能把已有信息丢掉。
        item.qtype = item.qtype or span.qtype
        item.score = item.score if item.score is not None else span.score
        item.needs_review = bool(item.error or item.warnings)
        return item

    tasks = [run_one(span) for span in boundary.spans]

    if tasks:
        # return_exceptions=False：取消信号必须能把整批带出来；
        # 单题的模型错误已经在 run_one 内部吞掉了。
        items = list(await asyncio.gather(*tasks))

    for item in items:
        if item.error:
            logger.info("qid=%s 结构化失败：%s", item.qid, item.error)
    return items
