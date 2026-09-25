"""答案区插图归属。

实测背景（2022 天津和平一模）：
- 第 20 题卷面「【答案】」下面就是一幅标了 R₁=15Ω、R₂=10Ω 的电路图，文字侧为空；
- 第 24 题 (2)(3) 的答案写「如上图所示」「如上图2 所示」，真正的电路图与描点
  图象在第 34 页的【解答】里；
- 第 26 题 (1) 的答案「如图」指答案区重印题干上方那张受力分析图。
这三道题在产物里连图都没有，因为 FigureExtractor 只处理正文题目记录。
"""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image

from app.services.api_extract.answer_figures import (
    answer_needs_figures,
    answer_region_blocks,
    extract_answer_figures,
    plan_answer_figures,
)
from physics_paper_splitter.lines import TextLine


def _line(line_id: int, page_index: int, y0: float, text: str) -> TextLine:
    return TextLine(
        line_id=line_id,
        page_index=page_index,
        y0=y0,
        y1=y0 + 12.0,
        x0=72.0,
        x1=400.0,
        text=text,
    )


def _png_bytes(offset: int = 0) -> bytes:
    """一张有内容的图；纯色会被 is_blank_image 当空白装饰丢掉。

    不同 offset 产出不同字节：PyMuPDF 对相同字节流会复用同一个图对象，
    要造「两张不同的图」必须让内容真的不一样。
    """
    image = Image.new("RGB", (120, 90), "white")
    for x in range(10, 110):
        image.putpixel((x, 45), (0, 0, 0))
    for y in range(10, 80, 4):
        image.putpixel((offset % 100 + 10, y), (0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def two_page_pdf() -> fitz.Document:
    """第 1 页：19 题（带图）+ 20 题锚点；第 2 页：20 题延续，页首有答案图。"""
    payload = _png_bytes()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "19．（4 分）上一题", fontsize=10)
    page.insert_image(fitz.Rect(72, 80, 192, 170), stream=payload)
    page.insert_text((72, 600), "20．（4 分）答案是图", fontsize=10)
    second = doc.new_page()
    second.insert_image(fitz.Rect(72, 60, 192, 150), stream=payload)
    second.insert_text((72, 300), "【答案】", fontsize=10)
    second.insert_text((72, 330), "【分析】略", fontsize=10)
    return doc


def test_answer_needs_figures_covers_three_cases():
    assert answer_needs_figures("（2）如上图所示；（3）如上图2 所示", True)
    assert answer_needs_figures("（1）如图；", True)
    # 答案为空但在答案区找到了该题解析 -> 卷面答案不是图就是表格
    assert answer_needs_figures(None, True)
    # 答案为空且根本没找到解析 -> 是「没答案」，不是「答案是图」
    assert not answer_needs_figures(None, False)
    # 纯文字答案不配图
    assert not answer_needs_figures("6V；30Ω", True)
    assert not answer_needs_figures("D", True)


def test_blocks_split_by_number_anchor():
    lines = [
        _line(1, 0, 100, "19．（4 分）上一题题干"),
        _line(2, 0, 130, "【答案】104；1：4。"),
        _line(3, 0, 200, "20．（4 分）答案是图"),
        _line(4, 0, 230, "【答案】"),
    ]
    blocks = answer_region_blocks(lines)
    assert [number for number, _ in blocks] == [19, 20]
    assert [len(rows) for _, rows in blocks] == [2, 2]


def test_blocks_keep_repeated_numbers_separate():
    """分板块重新编号时同一题号出现多次，必须各自成块而不是合并。"""
    lines = [
        _line(1, 0, 100, "1．（3 分）例题解析第一题"),
        _line(2, 0, 130, "【答案】A"),
        _line(3, 0, 200, "1．（3 分）随堂检测第一题"),
        _line(4, 0, 230, "【答案】B"),
    ]
    blocks = answer_region_blocks(lines)
    assert [number for number, _ in blocks] == [1, 1]


def test_plan_finds_figure_above_the_answer_marker(two_page_pdf):
    """跨页题的答案图常排在【答案】上方，条带要覆盖到整页。"""
    lines = [
        _line(1, 0, 60, "19．（4 分）上一题题干"),
        _line(2, 0, 600, "20．（4 分）答案是图"),
        _line(3, 1, 300, "【答案】"),
        _line(4, 1, 330, "【分析】略"),
    ]
    plans, reused = plan_answer_figures(two_page_pdf, lines, {20})

    assert 20 in plans
    pages = {page_index for page_index, _ in plans[20]}
    assert 1 in pages, "第 2 页页首的答案图必须被收进来"
    clip = next(rect for page_index, rect in plans[20] if page_index == 1)
    assert clip.y0 < 100, "应当取整张图（图在【答案】上方），而不是与条带的交集"
    assert reused == {}, "没传 stem_xrefs 时不应排除任何图"


def test_plan_skips_repeated_numbers():
    """题号在答案区不唯一时放弃归属，避免把别的板块的图挂错题。"""
    lines = [
        _line(1, 0, 60, "1．（3 分）第一题"),
        _line(2, 0, 600, "1．（3 分）又一个第一题"),
    ]
    plans, reused = plan_answer_figures(_pdf_two_pages_fixture(), lines, {1})
    assert plans == {}
    assert reused == {}


def test_plan_ignores_unwanted_numbers(two_page_pdf):
    lines = [
        _line(1, 0, 600, "20．（4 分）答案是图"),
        _line(2, 1, 300, "【答案】"),
    ]
    plans, reused = plan_answer_figures(two_page_pdf, lines, set())
    assert plans == {}
    assert reused == {}


def _pdf_with_reprinted_stem_figure() -> tuple[fitz.Document, int]:
    """造一份「答案区重印题干图」的 PDF：两页引用同一个图对象（同 xref）。

    这是方案 C 要处理的重复裁图：答案区解答把题干配图重印一遍当讲解背景，
    题干已经裁过并挂在 figures 上，答案区不该再裁一份。判据就是 xref 相同。
    """
    payload = _png_bytes()
    doc = fitz.open()
    stem = doc.new_page()
    stem.insert_text((72, 60), "20．（4 分）答案是图", fontsize=10)
    stem.insert_image(fitz.Rect(72, 80, 192, 170), stream=payload)
    xref = stem.get_images(full=True)[0][0]

    answer = doc.new_page()
    # 引用同一图对象，而不是再插一份字节流 —— 只有同 xref 才是同一个图。
    answer.insert_image(fitz.Rect(72, 60, 192, 150), xref=xref)
    answer.insert_text((72, 300), "【答案】", fontsize=10)
    return doc, xref


def test_plan_drops_stem_figure_reprint():
    """题干图在答案区的重印件不进 plans，只登记到 reused。"""
    doc, xref = _pdf_with_reprinted_stem_figure()
    lines = [
        _line(1, 0, 60, "20．（4 分）答案是图"),
        _line(2, 1, 300, "【答案】"),
    ]
    plans, reused = plan_answer_figures(doc, lines, {20}, stem_xrefs={20: {xref}})

    assert plans == {}, "只有重印件时不该裁出任何答案图"
    assert reused == {20: {xref}}


def test_plan_keeps_new_answer_figure_beside_reprint():
    """答案区既有重印件、也有新画的图时，只排除重印件，保留新图。"""
    doc, xref = _pdf_with_reprinted_stem_figure()
    # 新图的矩形必须落在答案题块的行条带内，否则会被归属判据正常排除。
    doc[1].insert_image(fitz.Rect(72, 200, 192, 290), stream=_png_bytes(offset=30))
    lines = [
        _line(1, 0, 60, "20．（4 分）答案是图"),
        _line(2, 1, 300, "【答案】"),
    ]
    plans, reused = plan_answer_figures(doc, lines, {20}, stem_xrefs={20: {xref}})

    assert reused == {20: {xref}}
    assert len(plans.get(20, [])) == 1, "新画的答案图要留下"
    kept_rect = plans[20][0][1]
    assert kept_rect.y0 > 150, "留下的应当是下方那张新图，不是上面的重印件"


def test_extract_writes_files(two_page_pdf, tmp_path):
    lines = [
        _line(1, 0, 600, "20．（4 分）答案是图"),
        _line(2, 1, 300, "【答案】"),
    ]
    plans, _reused = plan_answer_figures(two_page_pdf, lines, {20})
    results = extract_answer_figures(two_page_pdf, plans, tmp_path)

    assert results[20], "应当裁出至少一张答案插图"
    for relative in results[20]:
        assert relative.startswith("figures/answer_Q020_")
        assert (tmp_path / Path(relative).name).exists()


def test_extract_returns_empty_for_no_plans(two_page_pdf, tmp_path):
    assert extract_answer_figures(two_page_pdf, {}, tmp_path) == {}


def _pdf_two_pages_fixture() -> fitz.Document:
    """重复题号用例只需要一张能开页的文档。"""
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    return doc


# ── 答案区优先（2026-09-12 用户拍板：答案区有图就只输出答案区的图）──────


@pytest.fixture()
def answer_vs_analysis_pdf() -> fitz.Document:
    """复刻和平卷第 20 题：【答案】标记旁一张电路图，【解答】正文里还有推导图。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "20．（6 分）题干", fontsize=10)
    # 答案图：紧贴【答案】标记上方（与标记行纵向重叠，浮动锚点漂移的常见排版）
    page.insert_image(fitz.Rect(72, 80, 260, 150), stream=_png_bytes(0))
    page.insert_text((72, 160), "【答案】", fontsize=10)
    page.insert_text((72, 195), "【解答】解：…得到暗箱内部电路连接如图丙：", fontsize=10)
    # 推导图：夹在【解答】与【点评】之间
    page.insert_image(fitz.Rect(72, 240, 260, 330), stream=_png_bytes(1))
    page.insert_text((72, 380), "【点评】略", fontsize=10)
    return doc


def test_plan_prefers_answer_marker_figure(answer_vs_analysis_pdf):
    """答案区（【答案】标记旁）有图 → 只取它，不把【解答】里的推导图掺进来。"""
    lines = [
        _line(1, 0, 55, "20．（6 分）题干"),
        _line(2, 0, 148, "【答案】"),
        _line(3, 0, 183, "【解答】解：…如图丙："),
        _line(4, 0, 375, "【点评】略"),
    ]
    plans, _reused = plan_answer_figures(answer_vs_analysis_pdf, lines, {20})
    assert set(plans) == {20}
    assert len(plans[20]) == 1, "推导图不该出现在答案图里"
    assert plans[20][0][1].y1 <= 160, "留下的应是紧贴【答案】上方那张图"


def test_plan_falls_back_to_analysis_figure_when_answer_region_has_none():
    """复刻第 24 题：【答案】处只有文字「如上图所示」，图在下一页【解答】里。"""
    doc = fitz.open()
    first = doc.new_page()
    first.insert_text((72, 60), "24．（6 分）题干", fontsize=10)
    first.insert_text((72, 300), "【答案】（2）如上图所示", fontsize=10)
    first.insert_text((72, 340), "【解答】如下图所示：", fontsize=10)
    second = doc.new_page()
    second.insert_image(fitz.Rect(72, 120, 260, 220), stream=_png_bytes(2))
    second.insert_text((72, 300), "【点评】略", fontsize=10)
    lines = [
        _line(1, 0, 55, "24．（6 分）题干"),
        _line(2, 0, 295, "【答案】（2）如上图所示"),
        _line(3, 0, 335, "【解答】如下图所示："),
        _line(4, 1, 100, "（4）根据图象，得出的结论是…"),
        _line(5, 1, 300, "【点评】略"),
    ]
    plans, _reused = plan_answer_figures(doc, lines, {24})
    assert set(plans) == {24}, "答案区没图时要靠引导词退回解析区取图"
    assert len(plans[24]) == 1


# ── 答案文本按小问分块（把图挂到 (2)(3) 下面）──────────────────────────


def test_split_and_assign_answer_blocks():
    from app.services.api_extract.answer_figures import (
        assign_answer_figures,
        split_answer_blocks,
    )

    blocks = split_answer_blocks(
        "（1）③；D；J（或K）；（2）如上图所示；（3）如上图2 所示；（4）成正比。"
    )
    assert [block["label"] for block in blocks] == ["（1）", "（2）", "（3）", "（4）"]
    assign_answer_figures(blocks, ["figures/a.webp", "figures/b.webp"])
    assert blocks[1]["figures"] == ["figures/a.webp"], "「如上图所示」的小问拿第一张"
    assert blocks[2]["figures"] == ["figures/b.webp"], "「如上图2 所示」的小问拿第二张"
    assert blocks[0]["figures"] == [] and blocks[3]["figures"] == []


def test_split_answer_blocks_without_subquestions():
    from app.services.api_extract.answer_figures import split_answer_blocks

    assert split_answer_blocks(None) == []
    assert split_answer_blocks("C") == [
        {"label": None, "text": "C", "figures": []}
    ]


# ── 答案区优先（2026-09-12 用户拍板：答案区有图就只输出答案区的图）──────


@pytest.fixture()
def answer_vs_analysis_pdf() -> fitz.Document:
    """复刻和平卷第 20 题：【答案】标记旁一张电路图，【解答】正文里还有推导图。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "20．（6 分）题干", fontsize=10)
    # 答案图：紧贴【答案】标记上方（与标记行纵向重叠，浮动锚点漂移的常见排版）
    page.insert_image(fitz.Rect(72, 80, 260, 150), stream=_png_bytes(0))
    page.insert_text((72, 160), "【答案】", fontsize=10)
    page.insert_text((72, 195), "【解答】解：…得到暗箱内部电路连接如图丙：", fontsize=10)
    # 推导图：夹在【解答】与【点评】之间
    page.insert_image(fitz.Rect(72, 240, 260, 330), stream=_png_bytes(1))
    page.insert_text((72, 380), "【点评】略", fontsize=10)
    return doc






# ── 答案文本按小问分块（把图挂到 (2)(3) 下面）──────────────────────────




