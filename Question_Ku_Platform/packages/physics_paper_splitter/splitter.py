from __future__ import annotations

import re

import pymupdf as fitz

from .models import CropSegment, DocumentInspection, QuestionAnchor, QuestionRecord


# 必须带题号标点；分值部分可选，以兼容少数只写“14．”的试卷。
# 扫描件文字层的题号分隔符常被 OCR 误识为 ：、，、，一并接受。
ANCHOR_RE = re.compile(
    r"^\s*(?:[（(]\s*多选\s*[）)])?\s*(\d{1,2})\s*(?:[．、：，,]|\.(?!\d))\s*"
    r"(?:[（(]\s*\d+\s*分\s*[）)])?"
)
HEADER_RE = re.compile(r"^\s*第\s*\d+\s*页")
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]+、")


def select_anchor_sequence(candidates: list[QuestionAnchor]) -> list[QuestionAnchor]:
    """选择从第 1 题开始、题号单调递增且整体最可信的锚点序列。

    旧实现遇到一个漏检题号后会丢弃其后的全部题目。这里使用带跳号惩罚的
    最长递增序列：连续题号得分最高，允许少量缺号，同时避免较早出现的伪
    锚点阻断后续真实题号。
    """
    ordered = sorted(candidates, key=lambda item: (item.page_index, item.y))
    if not ordered:
        return []

    scores: list[float | None] = [None] * len(ordered)
    previous: list[int | None] = [None] * len(ordered)
    lengths = [0] * len(ordered)
    gap_counts = [0] * len(ordered)

    for index, candidate in enumerate(ordered):
        if candidate.number == 1:
            scores[index] = 10.0
            lengths[index] = 1
        for prior_index in range(index):
            prior_score = scores[prior_index]
            prior = ordered[prior_index]
            if prior_score is None or prior.number >= candidate.number:
                continue
            gap = candidate.number - prior.number - 1
            score = prior_score + 10.0 - gap
            length = lengths[prior_index] + 1
            gaps = gap_counts[prior_index] + gap
            current_key = (
                scores[index] if scores[index] is not None else float("-inf"),
                lengths[index],
                -gap_counts[index],
            )
            candidate_key = (score, length, -gaps)
            if candidate_key > current_key:
                scores[index] = score
                previous[index] = prior_index
                lengths[index] = length
                gap_counts[index] = gaps

    reachable = [index for index, score in enumerate(scores) if score is not None]
    if not reachable:
        return []
    best = max(
        reachable,
        key=lambda index: (scores[index], lengths[index], -gap_counts[index], ordered[index].number),
    )
    selected: list[QuestionAnchor] = []
    while best is not None:
        selected.append(ordered[best])
        best = previous[best]
    return list(reversed(selected))


class QuestionSplitter:
    """利用 PDF 文字行的坐标定位题号，并生成题目所覆盖的页面区间。"""

    def __init__(self, side_margin: float = 0.0, top_margin: float = 44.0, bottom_margin: float = 82.0):
        self.side_margin = side_margin
        self.top_margin = top_margin
        self.bottom_margin = bottom_margin

    def _content_bottom(self, page: fitz.Page) -> float:
        """返回正文可用下边界，优先贴着实际页脚而不是使用固定边距。"""
        fallback = page.rect.height - self.bottom_margin
        footer_tops: list[float] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                y0 = float(line.get("bbox", (0.0, 0.0, 0.0, 0.0))[1])
                if y0 >= page.rect.height * 0.75 and HEADER_RE.match(text):
                    footer_tops.append(y0)
        if footer_tops:
            # 留出极小空隙，避免把页脚抗锯齿像素带入题卡。
            return min(footer_tops) - 0.05
        return fallback

    def find_anchors(self, doc: fitz.Document, inspection: DocumentInspection) -> list[QuestionAnchor]:
        candidates: list[QuestionAnchor] = []
        for page_index in range(inspection.question_page_count):
            page = doc[page_index]
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = block.get("lines", [])
                logical_lines: list[tuple[str, float]] = []
                for line in lines:
                    spans = line.get("spans", [])
                    text = "".join(span.get("text", "") for span in spans)
                    # 某些公式 span 的 bbox 会异常向上扩张，导致整行 bbox 覆盖上一题。
                    # 题号位于首个非空 span，使用它的 y 坐标可避免把上一题尾行切进来。
                    first_span = next((span for span in spans if span.get("text", "").strip()), None)
                    y = float(first_span["bbox"][1] if first_span else line["bbox"][1])
                    logical_lines.append((text, y))

                # 少数 PDF 会把视觉上的“1．（1 分）”拆成多个并排文字行。
                # 对纯数字起始碎片，按横坐标重组同一高度的碎片后再尝试匹配。
                for line in lines:
                    spans = line.get("spans", [])
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not re.fullmatch(r"\d{1,2}", text):
                        continue
                    bbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
                    y0, y1 = float(bbox[1]), float(bbox[3])
                    fragments: list[tuple[float, str]] = []
                    for peer in lines:
                        peer_bbox = peer.get("bbox", (0.0, 0.0, 0.0, 0.0))
                        peer_y0, peer_y1 = float(peer_bbox[1]), float(peer_bbox[3])
                        if min(y1, peer_y1) <= max(y0, peer_y0):
                            continue
                        peer_text = "".join(span.get("text", "") for span in peer.get("spans", []))
                        fragments.append((float(peer_bbox[0]), peer_text))
                    rebuilt = "".join(value for _, value in sorted(fragments))
                    if rebuilt != text:
                        first_span = next((span for span in spans if span.get("text", "").strip()), None)
                        y = float(first_span["bbox"][1] if first_span else bbox[1])
                        logical_lines.append((rebuilt, y))

                seen: set[tuple[int, float]] = set()
                for text, y in logical_lines:
                    if HEADER_RE.match(text):
                        continue
                    match = ANCHOR_RE.match(text)
                    if not match:
                        continue
                    number = int(match.group(1))
                    key = (number, round(y, 2))
                    if not 1 <= number <= 99 or key in seen:
                        continue
                    seen.add(key)
                    candidates.append(QuestionAnchor(number, page_index, y, text.strip()))

        return select_anchor_sequence(candidates)

    @staticmethod
    def _find_section_breaks(doc: fitz.Document, question_page_count: int) -> list[tuple[int, float]]:
        """章节标题不属于任何一道题，用它截断上一题，避免标题混入题卡。"""
        breaks: list[tuple[int, float]] = []
        for page_index in range(question_page_count):
            for block in doc[page_index].get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    if SECTION_RE.match(text):
                        breaks.append((page_index, float(line["bbox"][1])))
        return breaks

    def build_records(
        self,
        doc: fitz.Document,
        inspection: DocumentInspection,
        anchors: list[QuestionAnchor],
    ) -> list[QuestionRecord]:
        records: list[QuestionRecord] = []
        section_breaks = self._find_section_breaks(doc, inspection.question_page_count)
        for index, anchor in enumerate(anchors):
            next_anchor = anchors[index + 1] if index + 1 < len(anchors) else None
            natural_end = (
                (next_anchor.page_index, next_anchor.y)
                if next_anchor
                else (inspection.question_page_count - 1, doc[inspection.question_page_count - 1].rect.height)
            )
            current_position = (anchor.page_index, anchor.y)
            intervening_breaks = [item for item in section_breaks if current_position < item < natural_end]
            effective_end = min(intervening_breaks) if intervening_breaks else natural_end
            end_page = effective_end[0]
            segments: list[CropSegment] = []

            for page_index in range(anchor.page_index, end_page + 1):
                page = doc[page_index]
                content_bottom = self._content_bottom(page)
                y0 = anchor.y - 4.0 if page_index == anchor.page_index else self.top_margin
                if page_index == effective_end[0]:
                    y1 = min(effective_end[1] - 5.0, content_bottom)
                else:
                    y1 = content_bottom
                if y1 - y0 < 4:
                    continue
                segments.append(
                    CropSegment(
                        page_index=page_index,
                        x0=self.side_margin,
                        y0=max(self.top_margin, y0),
                        x1=page.rect.width - self.side_margin,
                        y1=y1,
                    )
                )

            records.append(
                QuestionRecord(
                    number=anchor.number,
                    filename=f"Q{anchor.number:03d}.webp",
                    start_page=anchor.page_index + 1,
                    end_page=end_page + 1,
                    is_cross_page=end_page > anchor.page_index,
                    segments=segments,
                )
            )
        return records
