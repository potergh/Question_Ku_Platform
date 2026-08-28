from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from .cropper import QuestionCropper, save_webp
from .models import QuestionRecord

# 宽或高小于该值（PDF 点）的图片视为装饰元素（项目符号、边框），不单独提取。
DEFAULT_MIN_SIZE_PT = 40.0


def intersect_image_rects(
    image_rects: list,
    question_rect: fitz.Rect,
    min_size_pt: float = DEFAULT_MIN_SIZE_PT,
) -> list[fitz.Rect]:
    """求图片矩形与题目区域的交集；过小的装饰图按原图尺寸判定后剔除。"""
    results: list[fitz.Rect] = []
    for rect in image_rects:
        image_rect = fitz.Rect(rect)
        if image_rect.width < min_size_pt or image_rect.height < min_size_pt:
            continue
        intersection = image_rect & question_rect
        if intersection.is_empty or intersection.width <= 0 or intersection.height <= 0:
            continue
        results.append(intersection)
    return results


class FigureExtractor:
    """把题目区域内嵌位图按高清 DPI 裁出，独立保存到 figures/ 目录。

    矢量绘制图（常见电路图）不在 get_images 结果内，随题卡整图保留，不单独拆分。
    """

    def __init__(self, dpi: int = 300, webp_quality: int = 92, min_size_pt: float = DEFAULT_MIN_SIZE_PT):
        self.min_size_pt = min_size_pt
        # 复用题卡的渲染与白边收紧逻辑，保证插图与题卡视觉一致。
        self._cropper = QuestionCropper(dpi=dpi, webp_quality=webp_quality)

    def extract_all(self, doc: fitz.Document, records: list[QuestionRecord], figures_dir: Path) -> dict[int, list[str]]:
        figures_dir.mkdir(parents=True, exist_ok=True)
        return {record.number: self._extract_one(doc, record, figures_dir) for record in records}

    def _extract_one(self, doc: fitz.Document, record: QuestionRecord, figures_dir: Path) -> list[str]:
        paths: list[str] = []
        seen_xrefs: set[int] = set()
        counter = 0
        for segment in record.segments:
            page = doc[segment.page_index]
            question_rect = fitz.Rect(segment.x0, segment.y0, segment.x1, segment.y1)
            for image_info in page.get_images(full=True):
                xref = image_info[0]
                if xref in seen_xrefs:
                    continue
                try:
                    rects = intersect_image_rects(
                        page.get_image_rects(xref), question_rect, self.min_size_pt
                    )
                except Exception:
                    # 个别被遮罩或损坏的图片对象无法取矩形，跳过不影响其余内容。
                    continue
                if not rects:
                    continue
                seen_xrefs.add(xref)
                for rect in rects:
                    counter += 1
                    image = self._cropper._render_segment(page, rect)
                    name = f"Q{record.number:03d}_{counter:02d}.webp"
                    save_webp(image, figures_dir / name, self._cropper.webp_quality)
                    paths.append(f"figures/{name}")
        return paths
