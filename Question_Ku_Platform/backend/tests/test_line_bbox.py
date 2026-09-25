"""行 bbox 的纵向边界必须剔除异常扩张的公式 span。

背景（2026-09-13 修复）：和平卷第 8 页第 22 题的题干首行里有一个 CambriaMath
字体的「Ω」，它的 span bbox 带上了字体全局的 ascender/descender，高度 58.3pt，
而同行其余 span 只有 14pt。PyMuPDF 的 line bbox 是 span 并集，于是整行被撑成
y=(474.71, 511.31)，横跨了 Q21(2) 与 Q22 首行两个视觉行 —— 切题时 Q22 的首行
被划进上一题，题干从半句话开始（用户对着截图才发现）。

修复前的代码只把 y0 换成「首个非空 span 的 y」，y1 仍用未修正的 line bbox，
于是行高虚高 36.6pt。本测试锁住「y0 与 y1 都只由正常 span 决定」。
"""

from __future__ import annotations

from app.services.api_extract import ExtractCancelled  # noqa: F401
from physics_paper_splitter.lines import (
    SPAN_BBOX_HEIGHT_RATIO,
    _median_line_height,
    _span_vertical_bounds,
)


def _span(text: str, top: float, bottom: float, size: float = 10.4) -> dict:
    return {"text": text, "bbox": (0.0, top, 100.0, bottom), "size": size}


def test_abnormal_math_span_does_not_stretch_line():
    """混在正常 span 里的 CambriaMath「Ω」不得撑大行边界。"""
    spans = [
        _span("22", 474.71, 488.77),
        _span("．（6 分）如图所示电路中，小灯泡", 476.58, 487.03),
        # 异常 span：高度 58.3 ≈ 字号 × 5.6
        _span("Ω", 453.01, 511.31),
        _span("，当", 476.58, 487.03),
        _span(" 都闭合", 476.58, 487.87),
    ]
    y0, y1, trusted = _span_vertical_bounds(spans, [0.0, 453.01, 100.0, 511.31])
    assert trusted is True
    assert (y0, y1) == (474.71, 488.77)
    assert y1 - y0 < SPAN_BBOX_HEIGHT_RATIO * 10.4


def test_all_spans_abnormal_reports_untrusted():
    """整行 span 都异常时不能假装可信，交给调用方用页中位行高收紧。"""
    spans = [_span("Ω", 453.01, 511.31), _span("≈", 460.0, 508.0)]
    y0, y1, trusted = _span_vertical_bounds(spans, [0.0, 453.01, 100.0, 511.31])
    assert trusted is False
    assert y0 == 453.01  # 退回 line bbox，不丢行


def test_empty_spans_fall_back_to_line_bbox():
    y0, y1, trusted = _span_vertical_bounds([], [0.0, 100.0, 100.0, 114.0])
    assert trusted is False
    assert (y0, y1) == (100.0, 114.0)


def test_blank_spans_are_ignored():
    """空白 span 不参与边界计算（它们的 bbox 常常是整块区域）。"""
    spans = [_span("   ", 400.0, 500.0), _span("正文", 474.71, 488.77)]
    y0, y1, trusted = _span_vertical_bounds(spans, [0.0, 400.0, 100.0, 500.0])
    assert trusted is True
    assert (y0, y1) == (474.71, 488.77)


def test_superscript_span_is_normal():
    """上标/下标的高度约为字号的 1.35 倍，不能被误判为异常。"""
    spans = [_span("R", 474.71, 488.77), _span("2", 478.30, 488.80, size=7.8)]
    y0, y1, trusted = _span_vertical_bounds(spans, [0.0, 474.71, 100.0, 488.80])
    assert trusted is True
    assert (y0, y1) == (474.71, 488.80)
