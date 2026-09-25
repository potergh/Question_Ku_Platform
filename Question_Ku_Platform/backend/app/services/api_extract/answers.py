"""三源答案归一。

实测数据决定了为什么必须三源：25 页讲义上现有链路答案匹配 0/20，因为
inspector.ANSWER_MARKERS 只认「参考答案」等四个词、packages/answers.py 只按
整数题号 1..N 归并，而讲义的答案形态是每题后面行内的「【难度】★【答案】A」。
连 4 页试卷也是 0/8 —— 它根本没有文末答案区。

三个来源按「误配风险从低到高」排序：
1. inline      题目自己行内的【答案】/故选X/答案：  —— 零归并风险
2. inline_llm  逐题结构化时模型读到的 answer_inline —— 同一段文字，零归并风险
3. answer_key_llm  文末答案区经 LLM 按原文题号拆出 —— 按 label 精确归并
4. companion   独立答案文档（配对 source 跑同一条管线的产出）—— 按 label 归并
5. answer_key_regex 文末答案区经 packages/answers.py 按整数题号归并 —— 板块重启时最易错配

任何两个来源给出不同答案 -> conflict=True -> needs_review=True。宁可让用户多看一眼，
也不能把错答案静默入库（错答案会被组卷印出去）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from physics_paper_splitter.answers import parse_answers
from physics_paper_splitter.lines import TextLine, to_plain_text, to_prompt_text
from physics_paper_splitter.models import DocumentInspection

from .boundary import BoundaryResult
from .prompts import (
    ANSWER_KEY_SYSTEM,
    ARBITRATION_SYSTEM,
    answer_key_user_text,
    arbitration_user_text,
)
from .structure import StructuredItem
from .vlm_client import VLMError, call_vlm_json

logger = logging.getLogger(__name__)

# 来源优先级：数字越小越可信（误配风险越低）。
ORIGIN_PRIORITY = {
    "inline": 0,
    "inline_llm": 1,
    "answer_key_llm": 2,
    "companion": 3,
    "answer_key_regex": 4,
}

INLINE_ANSWER_RE = re.compile(r"【\s*答案\s*】\s*([^【\n]*)")
INLINE_EXPLAIN_RE = re.compile(r"【\s*(?:解析|分析|详解|点评|思路)\s*】\s*([^【]*)", re.S)
CHOICE_CONCLUSION_RE = re.compile(r"故选\s*[：:]?\s*([A-D]{1,5})")
ANSWER_COLON_RE = re.compile(r"^\s*(?:参考答案|答案)\s*[：:]\s*(.+?)\s*$")
# 判定「这一行本身就是下一个标记」，避免把标记行当成上一标记的内容。
MARKER_LINE_RE = re.compile(r"^\s*【[^】]{1,8}】")

# to_prompt_text 给每行加的坐标前缀。调用方应当传原始文字，但万一传了
# prompt 格式，前缀会让 ^ 锚定的正则失配、并把「#7 [p2 y=410]」当成答案，
# 错答案入库比缺答案危害大得多，因此在这里无条件剔一道。
PROMPT_LINE_PREFIX_RE = re.compile(r"^\s*#\d+\s*\[p\d+\s+y=[-\d.]+\]\s*")

# 答案区一次喂给模型的行数上限。整段兜底后答案区可达数百行（实测 669 行，
# 其中 14 页的行来自整页转写），一次请求必然超时；切片后单段失败只丢该段。
#
# 注意：那 14 页**不是扫描件**（实测其中仅 1 页没有文字层，其余 13 页是电子版，
# 只是 CambriaMath 公式的字形取不回），且整页转写是**合并行**的——原生 473 行
# 经转写后约 293 行，行数是减少而非增加。所以别把 669 行读成"转写撑大的"，
# 更不能据此去削减转写；反过来说，若改回保留原生行，答案区会涨到约 834 行、
# 切片数从 5 段变 7 段，反而更差。详见 scripts/_probe_discard_cost.py。
ANSWER_KEY_CHUNK_LINES = 150
# 分段并发上限：段间无依赖，串行跑 4 段只是白等。
# 实测：3 并发 90.4s → 4 并发 73.4s。收益有限且递减——这些段是长文本大输出，
# 受端点总吞吐约束，不是并发放不开。
ANSWER_KEY_CONCURRENCY = 4
# 相邻切片的重叠行数。题号与其答案被切到两段时会**两头落空**：前段模型只看到
# 题号、原文没给答案，按提示词规则 4 填 null；后段看不到题号，而提示词禁止补全
# 题号，该题直接没有条目（实测红桥卷 Q23 即为此症）。留重叠让任一道题至少在一
# 段里完整出现一次；重叠造成的重复条目由 _dedupe_entries 消掉。
ANSWER_KEY_CHUNK_OVERLAP = 20

# 行号式 label：模型把 to_prompt_text 的「#539」前缀当成题号时的产物。
ROW_MARKER_LABEL_RE = re.compile(r"^#\d+")

# 模型把 JSON 的 null 写成字符串时的产物。真答案不会是这几个词。
NULLISH_TEXT_RE = re.compile(r"^(?:null|none|undefined|nan)$", re.IGNORECASE)

# label 归一时要去掉的装饰字符：【例1】与 例1 与 1、 应当能对上号。
LABEL_NOISE_RE = re.compile(r"[\s【】\[\]()（）．\.、:：,，\-—_第题]*")
TRAILING_NUMBER_RE = re.compile(r"(\d+)\s*$")
# 题号在开头且后跟分隔符（14．/ 14、/ 14.）；前缀最多 4 个非数字字符，够放「（多选）」。
# 小问「（1）」后面是「）」不是分隔符，因此不会被误认成第 1 题。
LEADING_NUMBER_RE = re.compile(r"^\D{0,4}?(\d{1,3})\s*[．.、]")


@dataclass(slots=True)
class AnswerEvidence:
    """一条答案证据。同一道题可以有多条，来自不同源。"""

    origin: str
    label: str | None = None
    answer: str | None = None
    explanation: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ResolvedAnswer:
    """一道题归一后的答案。"""

    qid: int
    answer: str | None = None
    explanation: str | None = None
    origin: str | None = None
    evidences: list[AnswerEvidence] = field(default_factory=list)
    conflict: bool = False
    needs_review: bool = False
    note: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidences"] = [evidence.to_dict() for evidence in self.evidences]
        return data


# ── 源一：行内 ───────────────────────────────────────────────────────


def extract_inline(text: str) -> tuple[str | None, str | None]:
    """从题目自己的文字里抠出答案与解析。

    实测形态是「【难度】★【答案】A」「【解析】…」，标记可能出现在同一行，
    也可能标记与内容分成两行（【答案】换行 A），因此逐行扫描并允许向后取一行。

    传入的应当是该题的原始文字行；prompt 格式的坐标前缀会被剔掉（见
    PROMPT_LINE_PREFIX_RE）。
    """
    rows = [
        stripped
        for line in text.splitlines()
        if (stripped := PROMPT_LINE_PREFIX_RE.sub("", line.strip()))
    ]
    answer: str | None = None
    explanation_parts: list[str] = []

    for index, row in enumerate(rows):
        if answer is None:
            match = INLINE_ANSWER_RE.search(row)
            if match:
                answer = match.group(1).strip() or _next_content(rows, index)
                continue
            choice = CHOICE_CONCLUSION_RE.search(row)
            if choice:
                answer = choice.group(1).strip()
                continue
            colon = ANSWER_COLON_RE.match(row)
            if colon:
                answer = colon.group(1).strip()
                continue

        for explain_match in INLINE_EXPLAIN_RE.finditer(row):
            captured = explain_match.group(1).strip()
            if captured:
                explanation_parts.append(captured)

    # 整段兜底：解析可能跨行，行内正则只抓到第一行。
    if not explanation_parts:
        blob = "\n".join(rows)
        for explain_match in INLINE_EXPLAIN_RE.finditer(blob):
            captured = explain_match.group(1).strip()
            if captured:
                explanation_parts.append(captured)

    explanation = "\n".join(explanation_parts).strip() or None
    return (answer or None), explanation


def _next_content(rows: list[str], index: int) -> str:
    """标记行内容为空时，向后取第一行非标记文字。"""
    for row in rows[index + 1 : index + 3]:
        if MARKER_LINE_RE.match(row):
            break
        if row:
            return row
    return ""


# ── 源二：文末答案区 ─────────────────────────────────────────────────


def normalize_label(label: str | None) -> str:
    """把「【例1】」「例1、」「1．」归一成可比较的 key。"""
    return LABEL_NOISE_RE.sub("", (label or "")).lower()


def trailing_number(label: str | None) -> int | None:
    match = TRAILING_NUMBER_RE.search(normalize_label(label))
    return int(match.group(1)) if match else None


def leading_number(label: str | None) -> int | None:
    """取「题号 + 分隔符」开头的编号，如 14．（2 分）…… -> 14。

    模型常把整段题干塞进 label（"14．（2 分）如图所示，此时天平的读数为"），
    此时 normalize_label 对不上、trailing_number 又取不到（尾部没有数字）。
    只认「数字后紧跟 ．/．/、」的才算题号，因此 (1) 这类小问不会被误认成第 1 题。
    """
    match = LEADING_NUMBER_RE.search(label or "")
    return int(match.group(1)) if match else None


async def parse_answer_key_region(
    config: dict,
    lines: list[TextLine],
    boundary: BoundaryResult,
) -> list[dict]:
    """让 LLM 按原文题号拆文末答案区，返回 [{label, answer, explanation}]。

    必须走 LLM 而不是只靠 packages/answers.py：后者按整数题号 1..N 归并，
    讲义答案区里的「【例1】」「随堂检测 1」会被完全认错。

    答案区可能极长（整段兜底后实测 669 行），一次喂进去必然超时，所以按
    ANSWER_KEY_CHUNK_LINES 切片多次调用；单段失败只丢该段，不拖垮其余。
    """
    if not boundary.answer_key_line_ids:
        return []
    region_lines = [line for line in lines if line.line_id in boundary.answer_key_line_ids]
    if not region_lines:
        return []

    step = max(1, ANSWER_KEY_CHUNK_LINES - ANSWER_KEY_CHUNK_OVERLAP)
    chunks = [
        region_lines[offset : offset + ANSWER_KEY_CHUNK_LINES]
        for offset in range(0, len(region_lines), step)
    ]
    async def _one_chunk(index: int, chunk) -> list[dict]:
        origin = (
            "文末答案区"
            if len(chunks) == 1
            else f"文末答案区（第 {index}/{len(chunks)} 段）"
        )
        try:
            payload = await call_vlm_json(
                config,
                system=ANSWER_KEY_SYSTEM,
                user_text=answer_key_user_text(to_plain_text(chunk), origin=origin),
            )
        except VLMError as exc:
            logger.warning(
                "answer_key region parse failed (chunk %s/%s): %s", index, len(chunks), exc
            )
            return []

        rows = payload.get("answers") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            logger.warning("answer_key chunk %s/%s 未返回 answers 数组", index, len(chunks))
            return []
        return _rows_to_entries(rows)

    # 段与段完全独立（重叠造成的重复条目由 _dedupe_entries 消掉），串行是遗漏：
    # 4 段 × 25s = 100s 白等。gather 保序，去重结果与串行一致。
    semaphore = asyncio.Semaphore(ANSWER_KEY_CONCURRENCY)

    async def _guarded(index: int, chunk) -> list[dict]:
        async with semaphore:
            return await _one_chunk(index, chunk)

    groups = await asyncio.gather(
        *(_guarded(index, chunk) for index, chunk in enumerate(chunks, start=1))
    )
    entries: list[dict] = [row for group in groups for row in group]
    return _dedupe_entries(entries)


def _dedupe_entries(entries: list[dict]) -> list[dict]:
    """按 (label, answer, explanation) 去重，消掉切片重叠带来的重复条目。

    只去**完全相同**的条目：板块重启时同一题号会有两份内容不同的答案，
    那是真条目，必须保留，否则匹配池变浅、真答案反而排不上。
    """
    seen: set[tuple] = set()
    unique: list[dict] = []
    for entry in entries:
        key = (entry.get("label"), entry.get("answer"), entry.get("explanation"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _clean_text(value) -> str | None:
    """把模型给的字段值收敛成「有内容的字符串」或 None。

    模型偶尔把 JSON 的 null 写成字符串，"null" 一路 truthy 下去会被当成答案
    存进 answer 字段。空串、"null"/"None"/"undefined"/"NaN" 一律视为无内容。
    注意「见试题解答内容」是原文里真实存在的占位说明，不在过滤之列。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or NULLISH_TEXT_RE.match(text):
        return None
    return text


def _rows_to_entries(rows: list) -> list[dict]:
    """答案区模型响应的原始行 -> 内部条目，非法项与行号式 label 直接丢弃。

    模型在长段里会把 to_prompt_text 的「#539」前缀当成题号，实测 247 条里
    218 条是这种垃圾。它们撑爆匹配池，真答案反而排不上。
    """
    entries: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip() or None
        if label and ROW_MARKER_LABEL_RE.match(label):
            continue
        entries.append(
            {
                "label": label,
                "answer": _clean_text(row.get("answer")),
                "explanation": _clean_text(row.get("explanation")),
            }
        )
    return entries


def parse_answer_key_deterministic(
    doc,
    lines: list[TextLine],
    boundary: BoundaryResult,
    pdf_path: Path,
) -> dict[int, dict]:
    """复用 packages/answers.py 的确定性解析，按整数题号返回。

    用一个合成的 DocumentInspection 把答案起始页喂进去 —— parse_answers 只读
    answer_start_page 与 len(doc)，不碰 pages，因此合成对象是安全的。
    讲义的分板块编号它认不对，所以只作为交叉校验证据，不作为首选。
    """
    if not boundary.answer_key_line_ids:
        return {}
    answer_pages = [
        line.page_index
        for line in lines
        if line.line_id in boundary.answer_key_line_ids
    ]
    if not answer_pages:
        return {}
    inspection = DocumentInspection(
        pdf_path=pdf_path,
        page_count=len(doc),
        question_page_count=min(answer_pages),
        answer_start_page=min(answer_pages) + 1,
        pages=[],
    )
    try:
        return parse_answers(doc, inspection).get("questions", {})
    except Exception as exc:  # noqa: BLE001 — 交叉校验失败不应中断主流程
        logger.warning("deterministic answer parse failed: %s", exc)
        return {}


# ── 源三：独立答案文档 ───────────────────────────────────────────────


def load_companion_entries(extract_json_path: Path | str | None) -> list[dict]:
    """从配对答案文档的暂存结果里取答案条目。

    答案文档跑的是同一条管线，它自己的「题目」就是逐条答案，因此直接取
    items[].label / answer / explanation 作为本试卷的第三答案源。
    """
    if not extract_json_path:
        return []
    path = Path(extract_json_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("companion extract.json unreadable (%s): %s", path, exc)
        return []

    entries: list[dict] = []
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        answer = item.get("answer")
        explanation = item.get("explanation")
        if not answer and not explanation:
            continue
        entries.append(
            {
                "label": item.get("label") or None,
                "answer": str(answer).strip() or None if answer else None,
                "explanation": str(explanation).strip() or None if explanation else None,
            }
        )
    return entries


# ── 归并 ─────────────────────────────────────────────────────────────


def _match_by_number(
    pending: list[tuple[int, str | None, str | None]],
    entries: list[dict],
    consumed: set[int],
    matched: dict[int, dict],
    per_item: dict[int, str],
    extract,
) -> list[tuple[int, str | None, str | None]]:
    """按编号数字唯一匹配一轮，返回仍未匹配的题。编号不唯一的留到下一轮。"""
    still: list[tuple[int, str | None, str | None]] = []
    for qid, label, section in pending:
        number = extract(label)
        hits = (
            [
                position
                for position, entry in enumerate(entries)
                if position not in consumed and extract(entry.get("label")) == number
            ]
            if number is not None
            else []
        )
        if len(hits) == 1:
            matched[qid] = entries[hits[0]]
            consumed.add(hits[0])
            per_item[qid] = f"按编号数字 {number} 匹配答案区条目，请核对"
        else:
            still.append((qid, label, section))
    return still


def match_entries(
    labels: list[tuple[int, str | None, str | None]],
    entries: list[dict],
) -> tuple[dict[int, dict], dict[int, str], list[str]]:
    """把答案条目按 label 归并到题目上。

    返回 (qid -> entry, qid -> 本题告警, 全局告警)。
    labels 是 [(qid, 原始 label, section)]。四级匹配：
    1. 归一后 label 精确相等；
    2. 前导题号数字相等且候选唯一；
    3. 尾部数字相等且候选唯一；
    4. 剩下的按文档顺序等量配对（数量不等就放弃，避免整体错位）。
    第 2、3、4 级都带误配风险，逐题记入告警供预览页标红。

    行号式 label（「#539」）在这里再拦一道：第 4 级是等量就配对，垃圾条目
    只要数量凑巧就能顺势顶上真答案的位置。
    """
    per_item: dict[int, str] = {}
    global_warnings: list[str] = []
    matched: dict[int, dict] = {}
    consumed: set[int] = set()

    entries = [
        entry
        for entry in entries
        if not (entry.get("label") and ROW_MARKER_LABEL_RE.match(str(entry["label"])))
    ]

    by_label: dict[str, list[int]] = {}
    for position, entry in enumerate(entries):
        key = normalize_label(entry.get("label"))
        if key:
            by_label.setdefault(key, []).append(position)

    pending: list[tuple[int, str | None, str | None]] = []
    for qid, label, section in labels:
        key = normalize_label(label)
        candidates = [p for p in by_label.get(key, []) if p not in consumed]
        if not candidates:
            pending.append((qid, label, section))
            continue
        matched[qid] = entries[candidates[0]]
        consumed.add(candidates[0])
        if len(candidates) > 1:
            # 同名 label 多次出现（板块重启）：按文档顺序取第一个未消费的。
            per_item[qid] = f"编号「{label}」在答案区出现多次，按顺序取了第一条"

    if not pending:
        return matched, per_item, global_warnings

    # 二级：按题号数字唯一匹配。前导数字优先于尾部数字 —— 模型常把整段题干
    # 塞进 label，此时尾部没有数字，只有题号在开头的数字能用。
    still_pending = _match_by_number(
        pending, entries, consumed, matched, per_item, leading_number
    )
    if still_pending:
        still_pending = _match_by_number(
            still_pending, entries, consumed, matched, per_item, trailing_number
        )

    # 三级：等量顺序配对
    leftovers = [position for position in range(len(entries)) if position not in consumed]
    if still_pending and len(still_pending) == len(leftovers):
        for (qid, _label, _section), position in zip(still_pending, leftovers):
            matched[qid] = entries[position]
            consumed.add(position)
            per_item[qid] = "编号对不上答案区，按出现顺序配对，请人工核对"
        global_warnings.append(
            f"有 {len(still_pending)} 道题的编号对不上答案区，已按出现顺序配对"
        )
    elif still_pending:
        global_warnings.append(
            f"有 {len(still_pending)} 道题未能匹配到答案区条目"
            f"（剩余答案条目 {len(leftovers)} 条）"
        )

    return matched, per_item, global_warnings


def _normalize_answer(answer: str | None) -> str:
    """比较用的答案归一：去空白、统一大小写、去尾部句读。"""
    if not answer:
        return ""
    return re.sub(r"[\s。．\.、;；,，]+$", "", answer.strip()).upper()


# 详略比较用的深度归一：去全部空白与标点、上标数字转普通数字（PDF 文字层
# 常把 10⁵ 丢成 105，LLM 那路则保留上标，不归一就比不了）。
_COMPACT_STRIP_RE = re.compile(r"[\s。．\.、;；,，:：！!？?（）()【】\[\]「」『』]+")
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _compact_text(answer: str | None) -> str:
    if not answer:
        return ""
    return _COMPACT_STRIP_RE.sub("", answer.translate(_SUPERSCRIPTS))


def _is_subsequence(needle: str, haystack: str) -> bool:
    """needle 的字符按序全部出现在 haystack 里（允许中间插入别的字符）。"""
    iterator = iter(haystack)
    return all(char in iterator for char in needle)


def _is_abbreviation(short: str, long: str) -> bool:
    """short 是 long 的缩略版（同一答案抄少了一截）。

    两个约束防误伤：长度差必须显著（1.5 倍，"ABD" vs "BD" 这种选择题漏字母
    的真冲突长度太接近，仍按冲突处理）；short 不能太短（"C" 是几乎所有选项
    串的子序列，短串一律不参与缩略判定）。
    """
    if len(short) < 6 or len(long) < len(short) * 3 // 2:
        return False
    return _is_subsequence(short, long)


def _same_answer_variant(a: str, b: str) -> bool:
    """两个版本的答案是同一内容（相等，或一方是另一方的缩略）。"""
    return a == b or _is_abbreviation(a, b) or _is_abbreviation(b, a)


def resolve_answers(
    labels: list[tuple[int, str | None, str | None]],
    structured: list[StructuredItem],
    *,
    inline_texts: dict[int, str],
    answer_key_llm: list[dict] | None = None,
    answer_key_regex: dict[int, dict] | None = None,
    companion_entries: list[dict] | None = None,
) -> tuple[list[ResolvedAnswer], list[str]]:
    """把三个来源的证据归一到每道题上，返回 (逐题结果, 全局告警)。

    Args:
        labels: [(qid, 原始 label, section)]，与 boundary.spans 对齐。
        structured: structure_questions 的产出，提供 inline_llm 证据。
        inline_texts: qid -> 该题全部行文本，用于行内正则。
        answer_key_llm: parse_answer_key_region 的产出。
        answer_key_regex: parse_answer_key_deterministic 的产出（按整数题号）。
        companion_entries: load_companion_entries 的产出。
    """
    evidences: dict[int, list[AnswerEvidence]] = {qid: [] for qid, _, _ in labels}
    notes: dict[int, list[str]] = {qid: [] for qid, _, _ in labels}
    global_warnings: list[str] = []

    def absorb(origin: str, entries: list[dict] | None) -> None:
        """把一个跨题归并的答案源合并进证据表。"""
        if not entries:
            return
        matched, per_item, warnings = match_entries(labels, entries)
        global_warnings.extend(warnings)
        empty = 0
        for qid, entry in matched.items():
            if qid not in evidences:
                continue
            if not (entry.get("answer") or entry.get("explanation")):
                # 条目在、但原文没给出可抄写的答案（卷面常写「见试题解答内容」）。
                # 静默 continue 会让用户永远不知道为什么答案是空的：逐题记一条，
                # 卡片上就会出现「警告」标记，复核时看得到原因。
                empty += 1
                notes[qid].append(f"答案区有本题编号，但原文没有可抄写的答案（{origin}）")
                continue
            evidences[qid].append(
                AnswerEvidence(
                    origin=origin,
                    label=entry.get("label"),
                    answer=entry.get("answer"),
                    explanation=entry.get("explanation"),
                )
            )
            if per_item.get(qid):
                notes[qid].append(per_item[qid])
        if empty:
            global_warnings.append(
                f"有 {empty} 道题在答案区只找到编号、没有可抄写的答案，已标为待复核"
            )

    # 源一：行内正则
    for qid, text in inline_texts.items():
        if qid not in evidences:
            continue
        answer, explanation = extract_inline(text)
        if answer or explanation:
            evidences[qid].append(
                AnswerEvidence(origin="inline", answer=answer, explanation=explanation)
            )

    # 源二之一：结构化时模型读到的行内答案
    for item in structured:
        if item.qid not in evidences:
            continue
        if item.answer_inline or item.explanation_inline:
            evidences[item.qid].append(
                AnswerEvidence(
                    origin="inline_llm",
                    answer=item.answer_inline,
                    explanation=item.explanation_inline,
                )
            )

    # 源二之二 / 源三：文末答案区与独立答案文档，都是跨题归并
    absorb("answer_key_llm", answer_key_llm)
    absorb("companion", companion_entries)

    # 源二之三：文末答案区的确定性解析（按整数题号），仅作交叉校验
    if answer_key_regex:
        number_to_qids: dict[int, list[int]] = {}
        for qid, label, _section in labels:
            # 题目 label 形如「23．（6 分）」：末尾是分值括号，trailing_number 取不到
            # 数字，只有 leading_number 认得。以前只看 trailing_number，于是带分值的
            # 试卷里这一路来源一条也配不上，还被报成「题号对应多道题」（实测红桥卷
            # 15 条全部如此）。
            number = trailing_number(label)
            if number is None:
                number = leading_number(label)
            if number is not None:
                number_to_qids.setdefault(number, []).append(qid)
        unpaired = 0
        clashed = 0
        for number, parsed in answer_key_regex.items():
            qids = number_to_qids.get(int(number), [])
            if not qids:
                unpaired += 1
                continue
            # 板块重启会让同一个整数对应多道题，此时整数归并不可信，直接跳过。
            if len(qids) > 1:
                clashed += 1
                continue
            qid = qids[0]
            if parsed.get("answer") or parsed.get("analysis"):
                evidences[qid].append(
                    AnswerEvidence(
                        origin="answer_key_regex",
                        label=str(number),
                        answer=parsed.get("answer"),
                        explanation=parsed.get("analysis"),
                    )
                )
        if unpaired:
            global_warnings.append(
                f"答案区有 {unpaired} 个题号没能与题目自动配对，"
                f"已跳过「按题号配对」这一路答案来源"
            )
        if clashed:
            global_warnings.append(
                f"文末答案区有 {clashed} 个题号在本文档里对应多道题（板块重启编号），"
                f"确定性解析已跳过这些题号"
            )

    resolved: list[ResolvedAnswer] = []
    for qid, _label, _section in labels:
        items = sorted(evidences[qid], key=lambda e: ORIGIN_PRIORITY.get(e.origin, 99))
        result = ResolvedAnswer(qid=qid, evidences=items)

        compact_answers = [_compact_text(e.answer) for e in items if e.answer]
        conflict = False
        for i in range(len(compact_answers)):
            for j in range(len(compact_answers)):
                if i == j:
                    continue
                if not _same_answer_variant(compact_answers[i], compact_answers[j]):
                    conflict = True
        if conflict:
            result.conflict = True
            notes[qid].append(
                "多个答案来源不一致："
                + " / ".join(f"{e.origin}={e.answer}" for e in items if e.answer)
            )

        primary = next((e for e in items if e.answer), None)
        if primary is not None:
            result.answer = primary.answer
            result.origin = primary.origin
            # 详略守卫：低优先级那路是原文完整句、高优先级那路抄了个摘要
            # （实测第 21 题被抄成「（1）8.4×10⁵J；（2）58.3min」，原文是
            # 「（1）正常工作时，水吸收的热量是…」），取完整的那版 —— 两路
            # 内容一致（缩略关系），只是抄多抄少，不违反「缺答案比错答案好」。
            for evidence in items:
                if evidence is primary or not evidence.answer:
                    continue
                if _is_abbreviation(
                    _compact_text(primary.answer), _compact_text(evidence.answer)
                ):
                    result.answer = evidence.answer
                    result.origin = evidence.origin
                    break
        for evidence in items:
            if result.explanation is None and evidence.explanation:
                result.explanation = evidence.explanation

        if not result.answer:
            result.needs_review = True
            notes[qid].append("未从任何来源找到答案")
        if notes[qid]:
            result.needs_review = True
            result.note = "；".join(notes[qid])
        resolved.append(result)

    return resolved, global_warnings


# ── 定向仲裁：只对已标记冲突的题追加一次裁判调用 ─────────────────────

# 仲裁时喂给裁判的题干/证据截断上限：裁判的任务是鉴别忠实度，不是读全文。
ARBITRATION_STEM_CHARS = 1500
ARBITRATION_EVIDENCE_CHARS = 800


@dataclass(slots=True)
class ArbitrationResult:
    """一道冲突题的仲裁结论。只写 note，不改 answer —— 终审权留给人工。"""

    qid: int
    verdict: str  # "A" / "B" / "unclear"
    reason: str
    adopted_origin: str | None = None  # verdict 为 A/B 时被采信一路的 origin


def _pick_arbitration_pair(resolved: ResolvedAnswer) -> tuple[AnswerEvidence, AnswerEvidence] | None:
    """从冲突题的证据里挑出前两条「答案真不一致」的证据（按优先级排好序）。"""
    answers = [e for e in resolved.evidences if e.answer]
    for i in range(len(answers)):
        for j in range(len(answers)):
            if i == j or _same_answer_variant(
                _compact_text(answers[i].answer), _compact_text(answers[j].answer)
            ):
                continue
            return answers[i], answers[j]
    return None


async def arbitrate_conflicts(
    config: dict,
    resolved: list[ResolvedAnswer],
    labels: list[tuple[int, str | None, str | None]],
    inline_texts: dict[int, str],
    *,
    cancel_check=None,
) -> tuple[list[ArbitrationResult], list[str]]:
    """对 conflict=True 的题逐道调用裁判模型，三态判决写进 note。

    设计约束（与「缺答案比错答案好」同源）：
    - 仲裁结论只追加在 note 上（「仲裁：…」），answer/origin/conflict 一律不动；
      verdict=unclear 或调用失败时冲突标记原样保留，needs_review 不降级。
    - 只对真正「答案互斥」的题发起：详略变体（_same_answer_variant）不算冲突，
      也不会进仲裁。
    """
    label_by_qid = {qid: label for qid, label, _section in labels}
    results: list[ArbitrationResult] = []
    warnings: list[str] = []

    for item in resolved:
        if not item.conflict:
            continue
        pair = _pick_arbitration_pair(item)
        if pair is None:
            continue
        evidence_a, evidence_b = pair
        if cancel_check is not None and await cancel_check():
            break

        def _render(evidence: AnswerEvidence) -> str:
            parts = [f"来源：{evidence.origin}", f"答案：{evidence.answer or '（无）'}"]
            if evidence.explanation:
                parts.append(
                    "解析：" + evidence.explanation[:ARBITRATION_EVIDENCE_CHARS]
                )
            return "\n".join(parts)

        user_text = arbitration_user_text(
            label=label_by_qid.get(item.qid),
            stem_text=(inline_texts.get(item.qid) or "")[:ARBITRATION_STEM_CHARS],
            evidence_a=_render(evidence_a),
            evidence_b=_render(evidence_b),
        )
        try:
            payload = await call_vlm_json(
                config, system=ARBITRATION_SYSTEM, user_text=user_text
            )
        except (VLMError, asyncio.TimeoutError) as exc:
            warnings.append(
                f"第 {label_by_qid.get(item.qid) or item.qid} 题仲裁调用失败，"
                f"冲突标记维持不变：{str(exc)[:120]}"
            )
            continue

        verdict = str(payload.get("verdict") or "").strip().upper() if isinstance(payload, dict) else ""
        reason = str(payload.get("reason") or "").strip() if isinstance(payload, dict) else ""
        if verdict not in ("A", "B", "unclear"):
            verdict = "unclear"
            reason = reason or "裁判返回了无法理解的结论"

        if verdict == "unclear":
            adopted = None
            note = f"仲裁：无法裁定（{reason[:80]}），维持冲突标记"
        else:
            adopted = (evidence_a if verdict == "A" else evidence_b).origin
            note = f"仲裁：采信 {adopted}（{reason[:80]}）"
        item.note = (item.note or "") + ("；" if item.note else "") + note
        results.append(
            ArbitrationResult(
                qid=item.qid, verdict=verdict, reason=reason, adopted_origin=adopted
            )
        )

    if results:
        warnings.append(
            f"已对 {len(results)} 道冲突题做定向仲裁，结论写在 answer_note 供人工终审参考"
            f"（答案字段未改动）。"
        )
    return results, warnings
