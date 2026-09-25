from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

from ..models import QuestionRecord
from .fusion import fuse
from .native import extract_native_text, native_quality
from .rapid import load_ocr_engine
from .structure import infer_question_type, parse_content


SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]+、.*$")

# 原生文字中替换字符 (U+FFFD) 超过此阈值，说明字体编码严重损坏，应回退到 OCR
_GARBLED_THRESHOLD = 3


def _select_best_text(native_text: str, ocr_text: str, native_score: float) -> str:
    """根据质量选择最佳文字源。

    策略：
    - 原生文字无乱码且质量高分 → 优先原生（保留 PDF 精确排版）
    - 原生文字含大量乱码 → 回退到 OCR（图片识别不依赖字体编码）
    - 两者都有问题时 → 选较长的（信息量更大）
    """
    garbled_count = native_text.count("\ufffd")

    # 原生文字严重损坏 → 回退 OCR
    if garbled_count >= _GARBLED_THRESHOLD and ocr_text:
        return ocr_text

    # 原生文字质量尚可 → 优先原生
    if native_text and native_score >= 0.7:
        return native_text

    # 原生文字为空或质量低 → 用 OCR
    if ocr_text:
        return ocr_text

    # 都没有就用原生（可能为空）
    return native_text


def _section_for_question(doc: fitz.Document, record: QuestionRecord) -> str | None:
    """查找题号之前最近的章节标题，用于判断题型。"""
    latest: tuple[int, float, str] | None = None
    for page_index in range(record.start_page):
        for block in doc[page_index].get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                y = float(line["bbox"][1])
                if page_index == record.start_page - 1 and y >= record.segments[0].y0:
                    continue
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if SECTION_RE.match(text):
                    latest = (page_index, y, text)
    return latest[2] if latest else None


class QuestionTextPipeline:
    """为题卡生成原生文字、可选本地 OCR、结构化字段和复核标记。"""

    def __init__(self, engine_mode: str = "auto"):
        self.engine = load_ocr_engine(engine_mode)

    def process(
        self,
        doc: fitz.Document,
        records: list[QuestionRecord],
        question_dir: Path,
        source_pdf: Path,
        figures_map: dict[int, list[str]] | None = None,
        answers_map: dict[int, dict] | None = None,
    ) -> dict:
        questions: list[dict] = []
        for record in records:
            native_text = extract_native_text(doc, record)
            native_score, warnings = native_quality(native_text, record.number)
            ocr_text = ""
            ocr_confidence: float | None = None
            if self.engine is not None:
                ocr_text, ocr_confidence = self.engine.recognize(question_dir / record.filename)

            # 根据质量选择最佳文字源（原生乱码严重时回退到 OCR）
            selected_text = _select_best_text(native_text, ocr_text, native_score)
            parsed = parse_content(selected_text)
            section = _section_for_question(doc, record)
            fusion = fuse(
                native_text,
                ocr_text,
                native_score,
                ocr_confidence if self.engine is not None else None,
            )
            needs_review = fusion.needs_review
            if not parsed["stem"]:
                needs_review = True
                warnings.append("未解析出题干。")

            questions.append(
                {
                    "id": f"{source_pdf.stem}_Q{record.number:03d}",
                    "number": record.number,
                    "type": infer_question_type(section),
                    "score": parsed["score"],
                    "location": {
                        "start_page": record.start_page,
                        "end_page": record.end_page,
                        "segments": [
                            {
                                "page": segment.page_index + 1,
                                "bbox": [segment.x0, segment.y0, segment.x1, segment.y1],
                            }
                            for segment in record.segments
                        ],
                    },
                    "content": {"stem": parsed["stem"], "options": parsed["options"]},
                    "assets": {
                        "card": f"questions/{record.filename}",
                        "figures": (figures_map or {}).get(record.number, []),
                    },
                    "answer": (answers_map or {}).get(record.number),
                    "text": {
                        "selected": selected_text,
                        "native": native_text,
                        "local_ocr": ocr_text,
                    },
                    "quality": {
                        "native_score": native_score,
                        "ocr_engine": self.engine.name if self.engine is not None else None,
                        "ocr_confidence": ocr_confidence,
                        "fusion": fusion.to_dict(),
                        "needs_review": needs_review,
                        "warnings": warnings,
                    },
                }
            )

        return {
            "schema_version": 2,
            "source_pdf": str(source_pdf.resolve()),
            "ocr_engine": self.engine.name if self.engine is not None else None,
            "question_count": len(questions),
            "review_count": sum(item["quality"]["needs_review"] for item in questions),
            "review_questions": [item["number"] for item in questions if item["quality"]["needs_review"]],
            "questions": questions,
        }
