from __future__ import annotations

import re

import pymupdf as fitz

from ..models import QuestionRecord


PAGE_FOOTER_RE = re.compile(r"第\s*\d+\s*页[（(]共\s*\d+\s*页[）)]")


def _strip_before_question(text: str, number: int) -> str:
    patterns = (
        rf"(?:[（(]\s*多选\s*[）)])?\s*{number}\s*[\.．、]",
        rf"(?:[（(]\s*多选\s*[）)])?\s*{number}\s*(?=[（(]\s*\d+\s*分)",
    )
    matches = [match for pattern in patterns if (match := re.search(pattern, text))]
    return text[min(match.start() for match in matches) :].lstrip() if matches else text


def extract_native_text(doc: fitz.Document, record: QuestionRecord) -> str:
    """按题目保存的原 PDF 坐标提取文字，保证与题卡边界一致。"""
    parts: list[str] = []
    for segment in record.segments:
        clip = fitz.Rect(segment.x0, segment.y0, segment.x1, segment.y1)
        text = doc[segment.page_index].get_text("text", clip=clip, sort=True)
        text = PAGE_FOOTER_RE.sub("", text)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if text:
            parts.append(text)
    return _strip_before_question("\n".join(parts).strip(), record.number)


def native_quality(text: str, expected_number: int) -> tuple[float, list[str]]:
    warnings: list[str] = []
    if not text:
        return 0.0, ["原生文字为空。"]

    score = 1.0
    replacement_count = text.count("�") + text.count("□")
    if replacement_count:
        score -= min(0.45, replacement_count * 0.08)
        warnings.append(f"原生文字包含 {replacement_count} 个异常替换字符。")

    if not re.match(
        rf"^\s*(?:[（(]多选[）)])?\s*{expected_number}\s*(?:[\.．、]|(?=[（(]\s*\d+\s*分))",
        text,
    ):
        score -= 0.25
        warnings.append("原生文字未以预期题号开头。")

    if len(text) < 12:
        score -= 0.25
        warnings.append("原生文字过短。")

    return round(max(0.0, score), 4), warnings
