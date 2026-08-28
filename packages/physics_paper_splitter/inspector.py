from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

from .models import DocumentInspection, PageInspection


ANSWER_MARKERS = ("参考答案与试题解析", "参考答案", "答案与解析", "试题解析")
QUESTION_RE = re.compile(r"(?:[（(]\s*多选\s*[）)])?\s*(\d{1,2})\s*[\.．、]\s*(?:[（(]\s*\d+\s*分\s*[）)])?")


class PDFInspector:
    """检查 PDF 的文字层、图片对象，以及题目页和答案页边界。"""

    def inspect(self, pdf_path: Path) -> DocumentInspection:
        pdf_path = pdf_path.resolve()
        pages: list[PageInspection] = []
        warnings: list[str] = []
        answer_start: int | None = None

        with fitz.open(pdf_path) as doc:
            for page_index, page in enumerate(doc):
                text = page.get_text("text")
                is_answer = any(marker in text for marker in ANSWER_MARKERS)
                if is_answer and answer_start is None:
                    answer_start = page_index

                numbers = [int(value) for value in QUESTION_RE.findall(text)]
                replacement_chars = text.count("�")
                # 第一阶段只标记风险，不自动触发 OCR。
                needs_ocr = len(text.strip()) < 20 or replacement_chars >= 3
                pages.append(
                    PageInspection(
                        page_index=page_index,
                        width=round(page.rect.width, 2),
                        height=round(page.rect.height, 2),
                        text_chars=len(text),
                        image_count=len(page.get_images(full=True)),
                        replacement_chars=replacement_chars,
                        question_numbers=numbers,
                        is_answer_page=is_answer,
                        needs_ocr=needs_ocr,
                    )
                )

            if answer_start is None:
                warnings.append("未找到答案解析起始页，将整份 PDF 视为题目页。")
                question_page_count = len(doc)
            else:
                question_page_count = answer_start

            if question_page_count == 0:
                warnings.append("答案标记出现在第一页，未找到题目页。")

            return DocumentInspection(
                pdf_path=pdf_path,
                page_count=len(doc),
                question_page_count=question_page_count,
                answer_start_page=(answer_start + 1) if answer_start is not None else None,
                pages=pages,
                warnings=warnings,
            )
