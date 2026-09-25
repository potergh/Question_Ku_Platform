"""页面路由判定的回归测试：扫描页必须被判成 vlm，否则永远不会被转写。

被真实样本打脸过一次：组卷站点的追踪水印（``{#{...}#}``，每页 58 字符）
让纯扫描件在「文字层字符数」上看起来像有文字，旧判据（< 20 字符）被骗过，
页面判成 native → 不走视觉模型转写 → 行清单只剩水印 → 整份文档被判为
非题目区 → 切出 0 题，而覆盖率因 total_lines==0 恒为 100%，验收照样 PASS。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pymupdf as fitz
import pytest

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from physics_paper_splitter.inspector import (  # noqa: E402
    ANSWER_MARKER_HEAD_CHARS,
    MIN_NATIVE_CHARS,
    WATERMARK_RE,
    PDFInspector,
    split_vlm_pages,
)

# 学科网/组卷网实测水印串，每页都塞同样一段。
WATERMARK = "{#{QQABQYSwxgo4kISACI5LE0E8CQqYkIGhJOgExVAZuAwCyZNIFIA=}#}"
BODY_TEXT = "如图所示，电源电压为 6V 保持不变，闭合开关 S 后，电流表读数为 0.3A。" * 3


def _make_pdf(tmp_path: Path, page_texts: list[str]) -> Path:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 100), text, fontsize=11)
    path = tmp_path / "sample.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_watermark_only_page_routes_to_vlm(tmp_path):
    """只有水印的扫描页：剥离后 0 字符，必须判 vlm。"""
    pdf = _make_pdf(tmp_path, [WATERMARK] * 3)
    inspection = PDFInspector().inspect(pdf)

    assert [page.route for page in inspection.pages] == ["vlm"] * 3
    assert all(page.needs_ocr for page in inspection.pages)


def test_real_text_layer_routes_to_native(tmp_path):
    """有真文字层的页不该被送去转写，否则白白烧调用。"""
    assert len(BODY_TEXT.strip()) > MIN_NATIVE_CHARS
    pdf = _make_pdf(tmp_path, [BODY_TEXT] * 2)
    inspection = PDFInspector().inspect(pdf)

    assert [page.route for page in inspection.pages] == ["native"] * 2


def test_watermark_is_stripped_before_counting(tmp_path):
    """水印字符不能计入「有效文字」，否则扫描件会撑过阈值。"""
    pdf = _make_pdf(tmp_path, [WATERMARK + "第 1 页"])
    inspection = PDFInspector().inspect(pdf)

    assert WATERMARK_RE.sub("", WATERMARK + "第 1 页").strip() == "第 1 页"
    assert inspection.pages[0].text_chars >= len(WATERMARK)
    assert inspection.pages[0].route == "vlm"


class _FakePage:
    """只有 inspector 用到的那三个属性，避免为测文本判据去造真 PDF。"""

    def __init__(self, text: str):
        self._text = text
        self.rect = SimpleNamespace(width=595.0, height=842.0)

    def get_text(self, *_args, **_kwargs):
        return self._text

    def get_images(self, *_args, **_kwargs):
        return []


class _FakeDoc:
    def __init__(self, texts):
        self._pages = [_FakePage(text) for text in texts]

    def __enter__(self):
        return self._pages

    def __exit__(self, *_args):
        return False

    def __len__(self):
        return len(self._pages)


def _inspect_texts(monkeypatch, texts):
    from physics_paper_splitter import inspector as inspector_mod

    monkeypatch.setattr(inspector_mod.fitz, "open", lambda *a, **k: _FakeDoc(texts))
    return PDFInspector().inspect(Path("dummy.pdf"))


def test_answer_marker_in_page_head_sets_answer_start(monkeypatch):
    """答案标记出现在首屏标题位：该页起算答案区，题目页到此为止。"""
    inspection = _inspect_texts(
        monkeypatch,
        ["正文第一页内容" * 30, "参考答案与试题解析\n1．（3 分）……"],
    )

    assert inspection.answer_start_page == 2
    assert inspection.question_page_count == 1
    assert inspection.pages[1].is_answer_page


def test_answer_marker_outside_head_does_not_truncate(monkeypatch):
    """正文页页眉/页脚蹭到「参考答案」字样时不能整段砍掉题目。"""
    marker_at_tail = "x" * (ANSWER_MARKER_HEAD_CHARS + 50) + "参考答案"
    inspection = _inspect_texts(monkeypatch, [marker_at_tail])

    assert inspection.answer_start_page is None
    assert inspection.question_page_count == 1
    assert not inspection.pages[0].is_answer_page


@pytest.mark.parametrize(
    "watermark",
    [
        "{#{QQABQYSwxgo4kISACI5LE0E8CQqYkIGhJOgExVAZuAwCyZNIFIA=}#}",
        "{#{ABC}#}",
        "{#{}#}",
    ],
)
def test_watermark_pattern_forms(watermark):
    assert WATERMARK_RE.sub("", watermark) == ""


def test_split_vlm_pages_separates_blank_from_broken_glyphs(monkeypatch):
    """vlm 的两种触发原因必须分开报：扫描件（真没文字层）vs 电子版（字形取不回）。

    实测被误报的规模：和平卷 13 页、南开卷 11 页、红桥卷 8 页 —— 它们剥离水印后的
    有效字符在 531~893 之间（文字层完好），却一直被报成「没有可用文字层」。
    合并成一句会让复核老师以为自己的卷子是扫描件。
    """
    # 页 1：只有水印 → 有效字符 0，真无文字层。
    # 页 2：文字层完好（远超阈值），只是混进 3 个 U+FFFD（CambriaMath 公式字形）。
    # 页 3：只有 2 个 U+FFFD，未达阈值 → 仍是 native，两个列表都不该有它。
    broken = "由I=" + "\ufffd" * 3 + "可得，电阻R1 的阻值：R1=30Ω。" * 8
    nearly = BODY_TEXT + "\ufffd" * 2
    inspection = _inspect_texts(monkeypatch, [WATERMARK, broken, nearly, BODY_TEXT])

    assert [page.route for page in inspection.pages] == ["vlm", "vlm", "native", "native"]
    # 触发原因的前提：页 2 不是"没文字"，它有大把可读文字。
    assert len(WATERMARK_RE.sub("", broken).strip()) > MIN_NATIVE_CHARS

    blank_pages, glyph_pages = split_vlm_pages(inspection)
    assert blank_pages == [1]
    assert glyph_pages == [2]
