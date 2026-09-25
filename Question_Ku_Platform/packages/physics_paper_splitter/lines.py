"""文字层行清单 —— 供 LLM 判定题目边界的输入。

与 splitter.find_anchors 共享同一套文字行提取技巧，但不做题号正则匹配：
边界判定权交给 LLM，本模块只负责给出「带页码与坐标的可靠行清单」。

LLM 不回传浮点坐标（易抄错），而是回传本清单里的 line_id，由调用方
反查得到 (page_index, y)，再交给 cropper 裁原图题卡。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import pymupdf as fitz

# 已知页码类噪声行；其余重复页眉页脚由 detect_running_lines 统计识别。
PAGE_NOISE_RE = re.compile(
    r"^\s*(?:"
    r"第\s*\d+\s*页(?:\s*[（(]?\s*共\s*\d+\s*页\s*[）)]?)?"
    r"|[（(]?\s*共\s*\d+\s*页\s*[）)]?"
    r"|\d{1,4}\s*/\s*\d{1,4}"
    r")\s*$"
)
# 页面底边缘的裸数字，且数值等于页序时判定为页码（实测：4 页卷页脚分别是 1/2/3/4）。
BARE_PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")

# 少数 PDF 会把视觉上的“1．（1 分）”拆成多个并排文字行，需要按横坐标重组。
NUMERIC_FRAGMENT_RE = re.compile(r"\d{1,2}")

# 重复行判定：出现在这么多页面的边缘区域即视为页眉/页脚。
RUNNING_LINE_PAGE_RATIO = 0.6
RUNNING_LINE_MIN_PAGES = 3
# 页眉/页脚所在的上下边缘区域，按页高比例划分。
EDGE_RATIO = 0.12

# 单个 span 的 bbox 高度超过「字号 × 本值」即判为异常 span。
# 成因实测：数学字体（CambriaMath）的 Ω 等符号会带上字体全局的
# ascender/descender，bbox 高度可达字号的 5 倍以上，把整行 bbox 撑到
# 跨越相邻两行（和平卷第 8 页第 22 题就是这么丢的题干首行）。
# 正常 span（含上标下标）高度普遍在字号的 1.0~1.5 倍，取 2.5 留足余量。
SPAN_BBOX_HEIGHT_RATIO = 2.5


@dataclass(slots=True)
class TextLine:
    """一行文字层文本及其位置。line_id 在整个文档内唯一且单调递增。"""

    line_id: int
    page_index: int
    y0: float
    y1: float
    x0: float
    x1: float
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _merge_fragments(
    lines: list[dict],
    idx: int,
) -> tuple[str, float, float, float, list[int]] | None:
    """把纯数字碎片行与同高度的并排碎片重组成一个逻辑行。

    返回 (文本, y0, x0, x1, 被消费的同行索引)；无法重组时返回 None。
    """
    line = lines[idx]
    spans = line.get("spans", [])
    text = "".join(span.get("text", "") for span in spans).strip()
    bbox = [float(value) for value in line.get("bbox", (0.0, 0.0, 0.0, 0.0))]
    y0, y1 = bbox[1], bbox[3]

    fragments: list[tuple[float, float, str]] = []
    consumed: list[int] = []
    for peer_index, peer in enumerate(lines):
        peer_bbox = [float(value) for value in peer.get("bbox", (0.0, 0.0, 0.0, 0.0))]
        peer_y0, peer_y1 = peer_bbox[1], peer_bbox[3]
        # 垂直方向无重叠的不是同一视觉行。
        if min(y1, peer_y1) <= max(y0, peer_y0):
            continue
        peer_text = "".join(span.get("text", "") for span in peer.get("spans", []))
        if not peer_text.strip():
            continue
        fragments.append((peer_bbox[0], peer_bbox[2], peer_text))
        consumed.append(peer_index)

    if len(fragments) < 2:
        return None
    fragments.sort()
    rebuilt = "".join(value for _, _, value in fragments)
    if rebuilt.strip() == text:
        return None

    first_span = next((span for span in spans if span.get("text", "").strip()), None)
    anchor_y = float(first_span["bbox"][1]) if first_span else y0
    return (
        rebuilt,
        anchor_y,
        min(x0 for x0, _, _ in fragments),
        max(x1 for _, x1, _ in fragments),
        consumed,
    )


def _span_vertical_bounds(
    spans: list[dict],
    line_bbox: list[float],
) -> tuple[float, float, bool]:
    """用「正常 span」重算一行的上下边界，剔除异常扩张的公式 span。

    PDF 里数学字体（CambriaMath 的 Ω 等）的 span 会带上字体全局的
    ascender/descender，bbox 高度可达字号的 5 倍以上；PyMuPDF 的 line bbox
    是 span 的并集，于是整行被撑成跨越相邻视觉行的「高个子行」——
    切题时表现为吞掉下一行、或把本题首行让给上一题（和平卷 Q22 即此形态）。

    Returns:
        (y0, y1, trusted)。trusted=False 表示整行 span 全部异常、边界只能
        退回 line 自身 bbox，调用方应当再用本页中位行高收一次紧。
    """
    normal: list[tuple[float, float]] = []
    for span in spans:
        if not span.get("text", "").strip():
            continue
        span_bbox = span.get("bbox") or ()
        if len(span_bbox) < 4:
            continue
        top, bottom = float(span_bbox[1]), float(span_bbox[3])
        size = float(span.get("size") or 0.0)
        if size > 0 and (bottom - top) > size * SPAN_BBOX_HEIGHT_RATIO:
            continue
        normal.append((top, bottom))

    if not normal:
        y0 = float(line_bbox[1])
        return y0, max(float(line_bbox[3]), y0 + 1.0), False

    y0 = min(top for top, _ in normal)
    y1 = max(bottom for _, bottom in normal)
    return y0, max(y1, y0 + 1.0), True


def _median_line_height(page: fitz.Page) -> float:
    """本页「可信行」的高度中位数，用于兜住整行 span 都异常的公式行。"""
    heights: list[float] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            bbox = [float(value) for value in line.get("bbox", (0.0, 0.0, 0.0, 0.0))]
            y0, y1, trusted = _span_vertical_bounds(line.get("spans", []), bbox)
            if trusted and y1 > y0:
                heights.append(y1 - y0)
    if not heights:
        return 0.0
    heights.sort()
    mid = len(heights) // 2
    if len(heights) % 2:
        return heights[mid]
    return (heights[mid - 1] + heights[mid]) / 2


def _logical_lines(page: fitz.Page) -> list[tuple[str, float, float, float, float]]:
    """返回 (文本, y0, y1, x0, x1) 列表，顺序与视觉阅读顺序一致。"""
    results: list[tuple[str, float, float, float, float]] = []
    fallback_height = _median_line_height(page)
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = block.get("lines", [])
        consumed: set[int] = set()
        for idx, line in enumerate(lines):
            if idx in consumed:
                continue
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans)
            bbox = [float(value) for value in line.get("bbox", (0.0, 0.0, 0.0, 0.0))]
            # 某些公式 span 的 bbox 会异常扩张，导致整行 bbox 覆盖相邻的视觉行。
            # y0 与 y1 都必须用「正常 span」重算 —— 只修 y0 会让行高虚高，
            # 切题时表现为把下一行吞进本题、或把本题首行让给上一题。
            y0, y1, trusted = _span_vertical_bounds(spans, bbox)
            if not trusted and fallback_height > 0:
                # 整行 span 都异常（解析区常见）：用本页中位行高收一次紧，
                # 免得这一行的 bbox 横跨相邻视觉行。
                if (y1 - y0) > fallback_height * SPAN_BBOX_HEIGHT_RATIO:
                    y1 = y0 + fallback_height

            if NUMERIC_FRAGMENT_RE.fullmatch(text.strip()):
                merged = _merge_fragments(lines, idx)
                if merged is not None:
                    merged_text, merged_y0, merged_x0, merged_x1, merged_indexes = merged
                    consumed.update(merged_indexes)
                    height = max(1.0, y1 - y0)
                    results.append((merged_text, merged_y0, merged_y0 + height, merged_x0, merged_x1))
                    continue

            if not text.strip():
                continue
            results.append((text, y0, y1, bbox[0], bbox[2]))
    return results


def detect_running_lines(
    lines: list[TextLine],
    page_count: int,
    page_heights: dict[int, float] | None = None,
) -> set[str]:
    """统计识别页眉/页脚：在多数页面的上下边缘重复出现的短文本。"""
    if page_count <= 0:
        return set()
    heights = page_heights or {}

    pages_per_text: dict[str, set[int]] = {}
    for line in lines:
        text = line.text.strip()
        # 页眉页脚通常很短；长句重复出现多半是真实内容（如题干模板）。
        if not text or len(text) > 30:
            continue
        height = heights.get(line.page_index, 0.0)
        if height <= 0:
            continue
        ratio = line.y0 / height
        if ratio > EDGE_RATIO and ratio < 1.0 - EDGE_RATIO:
            continue
        pages_per_text.setdefault(text, set()).add(line.page_index)

    threshold = max(RUNNING_LINE_MIN_PAGES, int(page_count * RUNNING_LINE_PAGE_RATIO))
    return {text for text, pages in pages_per_text.items() if len(pages) >= threshold}


def extract_line_inventory(
    doc: fitz.Document,
    page_range: range | None = None,
    drop_noise: bool = True,
) -> list[TextLine]:
    """提取整份文档（或指定页区间）的文字层行清单。

    Args:
        doc: 已打开的 PDF 文档。
        page_range: 页索引区间；None 表示全部页。
        drop_noise: 是否剔除页码行与统计识别出的页眉/页脚。
    """
    pages = page_range if page_range is not None else range(len(doc))
    page_heights = {index: float(doc[index].rect.height) for index in pages}

    raw: list[TextLine] = []
    for page_index in pages:
        for text, y0, y1, x0, x1 in _logical_lines(doc[page_index]):
            raw.append(
                TextLine(
                    line_id=-1,
                    page_index=page_index,
                    y0=round(y0, 2),
                    y1=round(y1, 2),
                    x0=round(x0, 2),
                    x1=round(x1, 2),
                    text=text.strip(),
                )
            )

    running = detect_running_lines(raw, len(pages), page_heights) if drop_noise else set()
    kept: list[TextLine] = []
    for line in raw:
        if not line.text:
            continue
        if drop_noise:
            height = page_heights.get(line.page_index, 0.0)
            ratio = (line.y0 / height) if height else 0.5
            in_edge = ratio <= EDGE_RATIO or ratio >= 1.0 - EDGE_RATIO
            in_bottom_edge = ratio >= 1.0 - EDGE_RATIO
            if in_edge and PAGE_NOISE_RE.match(line.text):
                continue
            if (
                in_bottom_edge
                and BARE_PAGE_NUMBER_RE.fullmatch(line.text)
                and int(line.text) == line.page_index + 1
            ):
                continue
            if line.text in running:
                continue
        kept.append(line)

    for order, line in enumerate(kept, start=1):
        line.line_id = order
    return kept


def to_prompt_text(lines: list[TextLine]) -> str:
    """渲染成喂给 LLM 的紧凑文本：每行一条，带 line_id、页码与 y 坐标。"""
    return "\n".join(
        f"#{line.line_id} [p{line.page_index + 1} y={line.y0:.1f}] {line.text}"
        for line in lines
    )


def to_plain_text(lines: list[TextLine]) -> str:
    """只拼行文字，不带 line_id / 页码 / 坐标前缀。

    答案区解析必须用这个而不是 to_prompt_text：实测模型在长段里会把
    「#539 [p14 y=...]」这类前缀当成题号输出，834 行的答案区能吐出 218 条
    label 全是行号的垃圾条目，直接把匹配池撑爆。
    """
    return "\n".join(line.text for line in lines)


def group_by_page(lines: list[TextLine]) -> dict[int, list[TextLine]]:
    """按页索引分组，保持行顺序。"""
    grouped: dict[int, list[TextLine]] = {}
    for line in lines:
        grouped.setdefault(line.page_index, []).append(line)
    return grouped


def lines_in_range(lines: list[TextLine], start_id: int, end_id: int) -> list[TextLine]:
    """取出 line_id 落在 [start_id, end_id] 的行（含端点）。"""
    return [line for line in lines if start_id <= line.line_id <= end_id]
