"""扫描件支持 — 为无文字层 PDF 构建隐形 OCR 文字层。

扫描件没有内嵌文字层，题号锚点检测无法工作。本模块把每页渲染成高清图，
用 OCR 引擎做整页识别，再把识别结果按坐标写回为"隐形文字层"
（render_mode=3：可选中、可检索，但不渲染显示，题卡外观不受影响）。
之后原有流水线（题号锚点切分、答案匹配等）无需任何修改即可工作。
"""

from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from PIL import Image

# 与 inspector 的 needs_ocr 阈值保持一致：单页文字少于该字符数视为无文字层。
MIN_PAGE_CHARS = 20

# 整页识别的渲染 DPI。200 足够识别正文小字，且比 300 快约一倍。
LAYER_DPI = 200


def ensure_text_layer(pdf_path: Path, output_path: Path, engine, dpi: int = LAYER_DPI) -> Path:
    """确保 PDF 有文字层；返回后续流水线应使用的 PDF 路径。

    - 有文字层的页面保持原样，直接返回原路径（不复制文件）。
    - 扫描页逐页整页 OCR，把结果写成隐形文字层，另存到 output_path。
    - 混合 PDF（部分页有文字层）只对空页补层。

    Args:
        pdf_path: 原始 PDF。
        output_path: 补层后的另存路径（建议放在 OCR 输出目录，随来源删除）。
        engine: OCR 引擎（需支持 recognize_lines）。扫描页存在但引擎为 None 时报错。
        dpi: 整页渲染分辨率。
    """
    with fitz.open(pdf_path) as doc:
        empty_pages = [
            index for index, page in enumerate(doc) if len(page.get_text().strip()) < MIN_PAGE_CHARS
        ]
        if not empty_pages:
            return pdf_path
        if engine is None:
            raise RuntimeError("PDF 没有文字层（扫描件），需要 OCR 引擎，请确认已安装 rapidocr_onnxruntime")

        scale = dpi / 72.0
        for page_index in empty_pages:
            page = doc[page_index]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            image = Image.open(BytesIO(pix.tobytes("png")))

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                image.save(tmp_path)
                lines = engine.recognize_lines(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            for box, text, _score in lines:
                text = text.strip()
                if not text:
                    continue
                xs = [point[0] for point in box]
                ys = [point[1] for point in box]
                left_pt = min(xs) / scale
                top_pt = min(ys) / scale
                height_pt = (max(ys) - min(ys)) / scale
                fontsize = max(6.0, height_pt)
                # insert_text 的坐标是基线位置，约为行顶 + 0.8 倍字号。
                baseline_pt = top_pt + fontsize * 0.8
                page.insert_text(
                    fitz.Point(left_pt, baseline_pt),
                    text,
                    fontname="china-s",
                    fontsize=fontsize,
                    render_mode=3,
                )

        doc.save(output_path)
    return output_path
