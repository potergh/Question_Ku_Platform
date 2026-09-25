"""PDF 水印清洗 —— 在光栅化之前把「自述为水印」的 Form XObject 中和掉。

背景：试卷 PDF 常带机构水印（实测红桥卷是「天津新东方」浅灰字样，每页 2 处）。
题卡图与插图都是**对页面矩形直接光栅化**（packages 的 QuestionCropper），水印会被
一起栅格化进图；而 packages 里已有的 recurring_xrefs() 只把跨页复现的图对象
**排除出插图候选**，既不抹像素，也管不到题卡裁剪。

做法：这类水印在 PDF 里是 Form XObject，导出工具会写
``/PieceInfo/ADBE_CompoundType/Private /Watermark``。把该 XObject 的流内容换成
``q Q``（什么都不画）即可让它消失 —— 注意**不是涂白**：水印是半透明地盖在正文上，
涂白会把底下的正文一起盖掉；中和 XObject 完全不影响页面内容流里的正文绘制。
实测（红桥卷第 22 页）：渲染像素差异只落在水印自身范围 x 111..487 / y 322..519 pt。

为什么放在 utils 而不是 packages：架构约定 OCR 包源码零改动（设计文档 §10.2），
清洗属于平台侧的输入预处理，本地 OCR 与大模型两条通道都受益。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

# 清洗副本放在原文件旁边的子目录里，**且保持同名**。
#
# 这不是洁癖：run_extract 与 OCRAdapter 都用 `pdf_path.stem` 推导输出目录
# （data/ocr_output/<stem>），改名会让重跑生成一个新目录、题卡资产 URL 全部失配。
CLEAN_DIR_NAME = ".clean"

# 判据是对象自述标记，不依赖文件名 —— 本机的命名是 KSPX*，换个导出工具就变了。
_WATERMARK_KEY = "PieceInfo/ADBE_CompoundType/Private"
_WATERMARK_VALUE = "Watermark"


def _is_watermark(doc: pymupdf.Document, xref: int) -> bool:
    """该 XObject 是否声明自己是水印。"""
    try:
        kind, value = doc.xref_get_key(xref, _WATERMARK_KEY)
    except Exception:  # noqa: BLE001 — 对象结构异常时按「不是水印」处理
        return False
    return kind != "null" and str(value).lstrip("/") == _WATERMARK_VALUE


def strip_watermarks(src: Path, dst: Path) -> int:
    """把 src 里所有自述为水印的 Form XObject 中和掉，另存为 dst。

    返回被中和的对象数；为 0 时不写 dst，调用方据此回退原文件
    （避免在上传目录里留下一份毫无意义的副本）。
    """
    src, dst = Path(src), Path(dst)
    doc = pymupdf.open(src)
    try:
        neutralized: set[int] = set()
        for page in doc:
            for entry in page.get_xobjects() or []:
                xref = entry[0]
                if xref in neutralized or not _is_watermark(doc, xref):
                    continue
                doc.update_stream(xref, b"q Q")
                neutralized.add(xref)
        if not neutralized:
            return 0
        dst.parent.mkdir(parents=True, exist_ok=True)
        doc.save(dst, garbage=3, deflate=True)
        return len(neutralized)
    finally:
        doc.close()


def prepare_pdf(src: Path) -> Path:
    """返回用于识别的 PDF：能清掉水印就给清洗副本，否则原文件。

    任何异常都回退原文件 —— 清洗是加分项，绝不能因为它让识别跑不起来。
    副本已存在且不旧于源文件时直接复用，避免每次重跑都重新解析整份 PDF。
    """
    src = Path(src)
    try:
        if not src.exists():
            return src
        dst = src.parent / CLEAN_DIR_NAME / src.name
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        removed = strip_watermarks(src, dst)
        if not removed:
            return src
        logger.info("水印清洗：中和 %d 个水印对象 -> %s", removed, dst)
        return dst
    except Exception as exc:  # noqa: BLE001
        logger.warning("水印清洗失败，改用原文件：%s", exc)
        return src
