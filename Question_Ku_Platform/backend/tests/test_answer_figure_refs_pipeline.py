"""「答案就是题干那张图」这条链路的端到端覆盖（方案 C 的产出字段）。

**为什么单独一个文件**：和平卷三道相关的题（20/24/26）的答案区**都还留着真正的
新图**（24 题是 (2) 电路图与 (3) 描点图象），所以 `answer_figure_refs` 字段在
真实产物里实测是空的。这意味着：

    plan_answer_figures → extract_answer_figures → plan_stem_figure_refs
      → _assemble_items → _serialize_item

这条链路**从来没被真实数据走通过**。字段要是坏掉，产物里看不出来、前端只会
「少一块」，也不会有人发现。本文件用一份「答案区只重印了题干图、没有任何新图」
的合成 PDF 把链路走满，每层断言都盯住同一个事实：

> 答案是题干那张图时，标注指向题干图，而不是再裁一份。

字段契约（前端 `ExtractReviewView.vue` 消费）：
    [{"stem_figure": "figures/Q020_01.webp", "stem_index": 1}]
序列化后补一个可直接点开的 `stem_figure_url`。
"""

from __future__ import annotations

import io

import pymupdf as fitz
from PIL import Image

from app.routers.extract import _serialize_item
from app.services.api_extract.answer_figures import (
    extract_answer_figures,
    plan_answer_figures,
    plan_stem_figure_refs,
)
from app.services.api_extract.boundary import BoundaryResult, QuestionSpan
from app.services.api_extract.service import _assemble_items
from app.services.api_extract_adapter import ExtractItemData
from physics_paper_splitter.lines import TextLine
from physics_paper_splitter.models import CropSegment, QuestionRecord

ANSWER_LINE_Y = 300.0


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
    """有内容的图；纯色会被 `is_blank_image` 当装饰丢掉。

    不同 offset 产出不同字节 —— PyMuPDF 对相同字节流复用同一 xref，
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


def _pdf_answer_reprints_stem(with_new_figure: bool) -> tuple[fitz.Document, int]:
    """第 1 页题干带图；第 2 页答案区把同一个图对象重印一遍。

    `with_new_figure=True` 时答案区额外插一张内容不同的新图（模拟和平卷第 24 题
    分析区里的 (2) 电路图），此时「如上图所示」指的是新图而非题干图。
    """
    payload = _png_bytes()
    doc = fitz.open()
    stem = doc.new_page()
    stem.insert_text((72, 60), "20．（4 分）答案是图", fontsize=10)
    stem.insert_image(fitz.Rect(72, 80, 192, 170), stream=payload)
    xref = stem.get_images(full=True)[0][0]

    answer = doc.new_page()
    # 引用同一图对象才是「重印」；再插一份字节流就变成两个 xref 了。
    answer.insert_image(fitz.Rect(72, 60, 192, 150), xref=xref)
    if with_new_figure:
        answer.insert_image(fitz.Rect(72, 200, 192, 290), stream=_png_bytes(offset=30))
    answer.insert_text((72, ANSWER_LINE_Y), "【答案】", fontsize=10)
    return doc, xref


def _answer_region_lines() -> list[TextLine]:
    """答案区行清单：题号锚点在题干页，【答案】标记在答案页。"""
    return [
        _line(1, 0, 60, "20．（4 分）答案是图"),
        _line(2, 1, ANSWER_LINE_Y, "【答案】"),
    ]


def _run_figure_stage(doc: fitz.Document, xref: int, tmp_path):
    """走完「排定 → 裁图 → 出引用标注」三步，返回 (kept, refs)。"""
    lines = _answer_region_lines()
    plans, reused = plan_answer_figures(doc, lines, {20}, stem_xrefs={20: {xref}})
    kept = extract_answer_figures(doc, plans, tmp_path)
    refs = plan_stem_figure_refs(
        reused,
        kept,
        figure_names={20: {xref: "figures/Q020_01.webp"}},
        figure_indexes={20: {xref: 1}},
    )
    return kept, refs


def test_pipeline_marks_stem_figure_when_nothing_else_left(tmp_path):
    """答案区只有题干图重印件：不裁图，产出指向题干图的标注。"""
    doc, xref = _pdf_answer_reprints_stem(with_new_figure=False)

    kept, refs = _run_figure_stage(doc, xref, tmp_path)

    assert kept == {}, "只有重印件时不该裁出任何答案图"
    assert refs == {20: [{"stem_figure": "figures/Q020_01.webp", "stem_index": 1}]}


def test_pipeline_stays_silent_when_a_new_answer_figure_exists(tmp_path):
    """答案区还有新图（如和平卷第 24 题的 (2)(3)）：保留新图，不加引用标注。

    这正是和平卷 `answer_figure_refs` 为空的真实原因 —— 不是 bug，
    是「如上图所示」指的是那张新图，再标一句「见题干图」会把人指错。
    """
    doc, xref = _pdf_answer_reprints_stem(with_new_figure=True)

    kept, refs = _run_figure_stage(doc, xref, tmp_path)

    assert len(kept.get(20, [])) == 1, "新画的答案图要留下"
    assert refs == {}, "该题还有新图时不该产出引用标注"


def test_referenced_figures_are_ordered_by_xref(tmp_path):
    """多个重印件时按 xref 排序，输出稳定才能比对与回归。"""
    doc, xref = _pdf_answer_reprints_stem(with_new_figure=False)
    refs = plan_stem_figure_refs(
        {20: {xref + 1, xref}},
        {},
        figure_names={20: {xref: "figures/Q020_01.webp", xref + 1: "figures/Q020_02.webp"}},
        figure_indexes={20: {xref: 1, xref + 1: 2}},
    )

    assert refs == {
        20: [
            {"stem_figure": "figures/Q020_01.webp", "stem_index": 1},
            {"stem_figure": "figures/Q020_02.webp", "stem_index": 2},
        ]
    }


def test_referenced_figures_drop_unknown_xref():
    """题号/文件名对不上时宁可不出标注，也不能产出指向空文件的路径。"""
    refs = plan_stem_figure_refs(
        {20: {999}},
        {},
        figure_names={20: {}},
        figure_indexes={20: {}},
    )

    assert refs == {}


def _make_boundary() -> BoundaryResult:
    return BoundaryResult(
        doc_kind="paper",
        spans=[
            QuestionSpan(
                qid=1,
                label="20．",
                section=None,
                qtype="解答题",
                score=4.0,
                start_line=1,
                end_line=2,
            )
        ],
        records=[
            QuestionRecord(
                number=20,
                filename="Q020.webp",
                start_page=1,
                end_page=1,
                is_cross_page=False,
                segments=[CropSegment(0, 72.0, 60.0, 400.0, 170.0)],
            )
        ],
    )


def test_assemble_items_carries_refs_onto_the_item():
    """拼装层要把引用标注带到条目上 —— 否则裁剪对、产物里也看不到。"""
    items = _assemble_items(
        _make_boundary(),
        structured=[],
        resolved=[],
        lines=_answer_region_lines(),
        card_paths={},
        figures_map={},
        answer_figures_map={},
        answer_figure_refs_map={1: [{"stem_figure": "figures/Q020_01.webp", "stem_index": 1}]},
    )

    assert len(items) == 1
    assert items[0].answer_figure_refs == [
        {"stem_figure": "figures/Q020_01.webp", "stem_index": 1}
    ]


def test_serialize_item_exposes_clickable_stem_figure_url(tmp_path):
    """序列化要把磁盘相对路径翻成前端能点开的 URL。"""
    item = ExtractItemData(
        qid=1,
        question_number=20,
        answer_figure_refs=[{"stem_figure": "figures/Q020_01.webp", "stem_index": 1}],
    )

    payload = _serialize_item(item, tmp_path, "src123")

    assert payload.answer_figure_refs == [
        {
            "stem_figure": "figures/Q020_01.webp",
            "stem_index": 1,
            "stem_figure_url": "/api/ocr-assets/src123/figures/Q020_01.webp",
        }
    ]


def test_serialize_item_drops_refs_without_stem_figure(tmp_path):
    """没带 stem_figure 的残条要丢掉，不能在前端渲染成一张裂图。"""
    item = ExtractItemData(
        qid=1,
        question_number=20,
        answer_figure_refs=[{"stem_index": 1}, {"stem_figure": "", "stem_index": 2}],
    )

    payload = _serialize_item(item, tmp_path, "src123")

    assert payload.answer_figure_refs == []
