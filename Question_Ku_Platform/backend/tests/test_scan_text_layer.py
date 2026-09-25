"""扫描件「补文字层」判据的回归测试。

与 `test_inspector_route.py` 同一根因的另一半：inspector 侧早已按
「剥离水印后的有效字符数 < 100」判断页面是否需要转写，但 `scan.ensure_text_layer`
仍用「原始字符数 < 20」的旧判据 —— 每页 58 字符的组卷站水印因此撑过阈值，
纯扫描件从不补层，本地 OCR 通道切出 0 题（实测：2026 河东区一模物理试卷）。

本文件同时锁住「两处判据必须同源」，避免再次分叉。
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from physics_paper_splitter import scan as scan_mod  # noqa: E402
from physics_paper_splitter.inspector import MIN_NATIVE_CHARS, WATERMARK_RE  # noqa: E402
from physics_paper_splitter.scan import ensure_text_layer  # noqa: E402

# 学科网/组卷网实测水印串，每页都塞同样一段（58 字符）。
WATERMARK = "{#{QQABQYSwxgo4kISACI5LE0E8CQqYkIGhJOgExVAZuAwCyZNIFIA=}#}"
BODY_TEXT = "如图所示，电源电压为 6V 保持不变，闭合开关 S 后，电流表读数为 0.3A。" * 3
INJECTED = "补层文字"


class _FakeEngine:
    """只实现补层用到的 `recognize_lines`，让测试不依赖 rapidocr 是否安装。"""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def recognize_lines(self, png_path):
        self.calls += 1
        assert Path(png_path).exists(), "补层前必须先把整页渲染成 PNG"
        box = [(40.0, 40.0), (300.0, 40.0), (300.0, 60.0), (40.0, 60.0)]
        return [(box, INJECTED, 0.99)]


def _make_pdf(tmp_path: Path, page_texts: list[str]) -> Path:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 100), text, fontsize=11)
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_watermark_only_pages_get_text_layer(tmp_path):
    """只有水印的扫描页必须补层（旧判据 58 > 20 会跳过，整卷切出 0 题）。"""
    pdf = _make_pdf(tmp_path, [WATERMARK, WATERMARK])
    engine = _FakeEngine()

    effective = ensure_text_layer(pdf, tmp_path / "layered.pdf", engine)

    assert engine.calls == 2, "两页都是扫描页，必须都补层"
    assert effective != pdf, "补层后应返回副本，而不是原文件"
    with fitz.open(effective) as doc:
        assert INJECTED in doc[0].get_text()


def test_real_text_layer_page_is_not_ocrd(tmp_path):
    """有真文字层的页不该被补层，否则白白烧掉 OCR 时间。"""
    pdf = _make_pdf(tmp_path, [BODY_TEXT])
    engine = _FakeEngine()

    effective = ensure_text_layer(pdf, tmp_path / "layered.pdf", engine)

    assert engine.calls == 0
    assert effective == pdf, "无需补层时应原文件直通（不复制）"


def test_hybrid_pdf_only_layers_empty_pages(tmp_path):
    """混合 PDF：只对没有文字层的页补层。"""
    pdf = _make_pdf(tmp_path, [BODY_TEXT, WATERMARK])
    engine = _FakeEngine()

    effective = ensure_text_layer(pdf, tmp_path / "layered.pdf", engine)

    assert engine.calls == 1
    with fitz.open(effective) as doc:
        assert INJECTED not in doc[0].get_text(), "有文字层的页不该被覆盖"
        assert INJECTED in doc[1].get_text()


def test_watermark_regex_is_shared_and_thresholds_are_intentionally_split():
    """水印正则必须同源；阈值则可不同，但必须各自成立。"""
    from physics_paper_splitter import inspector as inspector_mod

    # 正则同源：两处各写一份是本 bug 的成因（inspector 修了、scan 没修）
    assert scan_mod.WATERMARK_RE is inspector_mod.WATERMARK_RE
    # 关键语义：水印剥离后为 0 字符，必须低于 scan 的阈值才会触发补层
    assert len(WATERMARK_RE.sub("", WATERMARK).strip()) == 0
    assert len(WATERMARK_RE.sub("", WATERMARK).strip()) < scan_mod.MIN_PAGE_CHARS
    # 阈值刻意不同源：scan 保守（不在真文字页上叠加 OCR 层），
    # inspector 激进（宁可送 VLM 转写）。合并两者会让讲义稀疏页被重复叠字。
    assert scan_mod.MIN_PAGE_CHARS < MIN_NATIVE_CHARS
