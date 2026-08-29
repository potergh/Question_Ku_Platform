"""Preview service — PDF 转分页 PNG（PyMuPDF）。"""

from pathlib import Path


def pdf_page_count(pdf_path: Path) -> int:
    import pymupdf
    with pymupdf.open(pdf_path) as doc:
        return doc.page_count


def page_png(pdf_path: Path, index: int, scale: float = 2.0) -> bytes:
    """index 从 1 开始；越界抛 IndexError。"""
    import pymupdf
    with pymupdf.open(pdf_path) as doc:
        if index < 1 or index > doc.page_count:
            raise IndexError(f"page {index} out of range {doc.page_count}")
        pix = doc[index - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        return pix.tobytes("png")
