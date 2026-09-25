from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageChops

from .models import QuestionRecord

# WebP 格式单边像素上限（16383），超过会导致编码失败。
WEBP_MAX_SIDE = 16383


def save_webp(image: Image.Image, path: Path, quality: int) -> Image.Image:
    """保存为 WebP；超过格式上限时等比缩小后再编码，返回实际保存的图像。"""
    if image.width > WEBP_MAX_SIDE or image.height > WEBP_MAX_SIDE:
        scale = min(WEBP_MAX_SIDE / image.width, WEBP_MAX_SIDE / image.height)
        new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(new_size, Image.LANCZOS)
    image.save(path, "WEBP", quality=quality, method=6)
    return image


class QuestionCropper:
    """将一个题目的一个或多个页面片段渲染、收边并纵向拼接。"""

    def __init__(self, dpi: int = 300, webp_quality: int = 92, separator_px: int = 12, outer_padding_px: int = 18):
        self.dpi = dpi
        self.webp_quality = webp_quality
        self.separator_px = separator_px
        self.outer_padding_px = outer_padding_px

    @staticmethod
    def _trim_whitespace(image: Image.Image, padding: int = 18) -> Image.Image:
        rgb = image.convert("RGB")
        background = Image.new("RGB", rgb.size, "white")
        diff = ImageChops.difference(rgb, background).convert("L")
        # 忽略 JPEG/抗锯齿带来的近白噪声。
        diff = diff.point(lambda value: 0 if value < 18 else 255)
        bbox = diff.getbbox()
        if bbox is None:
            return rgb
        left, top, right, bottom = bbox
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(rgb.width, right + padding)
        bottom = min(rgb.height, bottom + padding)
        return rgb.crop((left, top, right, bottom))

    def _render_segment(self, page: fitz.Page, rect: fitz.Rect) -> Image.Image:
        pix = page.get_pixmap(dpi=self.dpi, clip=rect, alpha=False, colorspace=fitz.csRGB)
        image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        return self._trim_whitespace(image)

    def crop(self, doc: fitz.Document, record: QuestionRecord, output_dir: Path) -> Path:
        images: list[Image.Image] = []
        for segment in record.segments:
            rect = fitz.Rect(segment.x0, segment.y0, segment.x1, segment.y1)
            images.append(self._render_segment(doc[segment.page_index], rect))

        if not images:
            raise ValueError(f"第 {record.number} 题没有可渲染片段")

        target_width = max(image.width for image in images)
        # 这里只补白，绝不使用会缩放/裁边的适配方法；题图完整性优先。
        normalized: list[Image.Image] = []
        for image in images:
            if image.width == target_width:
                normalized.append(image)
                continue
            padded = Image.new("RGB", (target_width, image.height), "white")
            padded.paste(image, (0, 0))
            normalized.append(padded)
        total_height = sum(image.height for image in normalized) + self.separator_px * (len(normalized) - 1)
        canvas = Image.new("RGB", (target_width, total_height), "white")
        y = 0
        for image in normalized:
            canvas.paste(image, (0, y))
            y += image.height + self.separator_px

        # 最终再加一圈白边。它不会改变题目内容，只用于避免显示/压缩时贴边。
        framed = Image.new(
            "RGB",
            (canvas.width + self.outer_padding_px * 2, canvas.height + self.outer_padding_px * 2),
            "white",
        )
        framed.paste(canvas, (self.outer_padding_px, self.outer_padding_px))

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / record.filename
        saved = save_webp(framed, output_path, self.webp_quality)
        record.width_px, record.height_px = saved.size
        if record.height_px > 9000:
            record.warnings.append("图片高度超过 9000px，建议人工检查跨页边界。")
        return output_path
