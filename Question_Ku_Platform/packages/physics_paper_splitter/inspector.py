from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

from .models import DocumentInspection, PageInspection


ANSWER_MARKERS = ("参考答案与试题解析", "参考答案", "答案与解析", "试题解析")
QUESTION_RE = re.compile(r"(?:[（(]\s*多选\s*[）)])?\s*(\d{1,2})\s*[\.．、]\s*(?:[（(]\s*\d+\s*分\s*[）)])?")

# 组卷站点的追踪水印：形如 {#{QQABQYSwxgo4kISACI5LE0E8CQqYkIGhJOgExVAZuAwCyZNIFIA=}#}，
# 常见于学科网/组卷网导出的扫描件，每页都塞一段（实测每页 58 字符）。
# 它让纯扫描件在「文字层字符数」这个判据上看起来像有文字，从而被判成 native、
# 永远不走视觉模型转写 —— 结果是整份文档被判为非题目区、切出 0 题。
WATERMARK_RE = re.compile(r"\{#\{[^}]*\}#\}")

# 单页有效文字（剥离水印后）低于此值即视为没有可用文字层。
# 实测参照：有文字层的讲义每页约 765 字符、试卷每页约 558 字符；
# 纯扫描件剥离水印后为 0。阈值取 100 离两侧都很远。
MIN_NATIVE_CHARS = 100

# 答案标记只在页面前 N 个字符内认（首屏标题位）。
ANSWER_MARKER_HEAD_CHARS = 200


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
                # 只在首屏认答案标记：正文页的页眉/页脚偶尔也带「参考答案」字样，
                # 命中即截断会把后面的正文题目整段砍掉。
                is_answer = any(marker in text[:ANSWER_MARKER_HEAD_CHARS] for marker in ANSWER_MARKERS)
                if is_answer and answer_start is None:
                    answer_start = page_index

                numbers = [int(value) for value in QUESTION_RE.findall(text)]
                replacement_chars = text.count("�")
                # 判据必须先剥掉水印再数字符，否则扫描件会被水印撑过阈值。
                effective_chars = len(WATERMARK_RE.sub("", text).strip())
                needs_ocr = effective_chars < MIN_NATIVE_CHARS or replacement_chars >= 3
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
                        route="vlm" if needs_ocr else "native",
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


def split_vlm_pages(inspection: DocumentInspection) -> tuple[list[int], list[int]]:
    """把 ``route == "vlm"`` 的页按**触发原因**二分，返回 (无文字层的页号, 字形取不回的页号)。

    两者对用户是完全不同的信息，合并成一句会误导：

    - **无文字层**：扫描件/空页。复核老师需要知道"这卷是扫描的"；
    - **有文字层但字形取不回**：电子版页面，多为 CambriaMath 公式（Word 公式导出
      PDF 时，这些字形在字体表里给不出可用 Unicode，PyMuPDF 只能吐 U+FFFD）。
      与"是不是扫描件"无关。实测和平卷 13 页、南开 11 页、红桥 8 页都属此类，
      却一直被报成"没有可用文字层"。

    ``replacement_chars >= 3`` 是 ``needs_ocr`` 的**充分条件**，所以未命中该条者
    只可能是「有效字符 < MIN_NATIVE_CHARS」。

    已知边界：一页若同时满足两条（有效字符 < 100 **且** 替换字符 >= 3，即真扫描件
    里混了几个乱码字），会被归到"字形取不回"。要精确区分得让 ``PageInspection``
    存下 ``effective_chars``（本函数所在的 ``inspect`` 里算完就丢了）；现有 5 份
    样本上没有这种页，故先不为此改 schema。

    页号 **1-based** 且已排序，可直接写进面向用户的话术。
    """
    blank: list[int] = []
    glyph: list[int] = []
    for page in inspection.pages:
        if page.route != "vlm":
            continue
        (glyph if page.replacement_chars >= 3 else blank).append(page.page_index + 1)
    return sorted(blank), sorted(glyph)
