"""边界避让插图：题卡底边界切穿插图时上移让开。

实测动机（2026-09-24）：暑秋讲义「物-9暑-05-固体、液体压强选择」第 27 题，
【答案】C 早已结束，题卡右下角却多出四条短桩 —— 那是后一题（【例4】）两个
容器的四道侧壁。讲义是双栏排版，右栏的插图可以横跨左栏题号所在的水平线，
而「上一题底边界 = 下一题首行 y0 - GAP」只看文字行，看不到图。
实测该讲义 75 题里有 4 处这样的切穿；其中 3 处（题 27 / 36 / 55）图大部分在
边界之下，属于"被切进来一角"，正是本函数要处理的对象。

自限三条（每条都有对应用例）：只上移不下移、上移后仍要含住本题末行、
位移不超过 FIGURE_SNAP_MAX_SHIFT；另加一条归属判据 —— 只避让"大部分落在
边界之下"的图，否则等于把本题自己的插图推出卡外。
"""

from __future__ import annotations

import pymupdf as fitz

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from app.services.api_extract.boundary import (
    FIGURE_CLEARANCE,
    FIGURE_SNAP_MAX_SHIFT,
    avoid_figure_cuts,
)
from physics_paper_splitter.lines import TextLine
from physics_paper_splitter.models import CropSegment, QuestionRecord

PAGE_W, PAGE_H = 595.0, 842.0


def _doc_with_figure(x0: float, y0: float, x1: float, y1: float) -> fitz.Document:
    """一页 PDF，页面上只画一个矩形当作插图（矢量，和 Word 导出的讲义同类）。"""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=0.5)
    return doc


def _records(*spans: tuple[int, float, float]) -> list[QuestionRecord]:
    """spans 是 (题号, 片段 y0, 片段 y1)，都在第 0 页。"""
    return [
        QuestionRecord(
            number=number,
            filename=f"questions/Q{number:03d}.webp",
            start_page=0,
            end_page=0,
            is_cross_page=False,
            segments=[CropSegment(0, 0.0, y0, PAGE_W, y1)],
        )
        for number, y0, y1 in spans
    ]


def _lines(*pairs: tuple[float, float]) -> dict[int, list[TextLine]]:
    return {
        0: [
            TextLine(index, 0, y0, y1, 0.0, PAGE_W, f"第 {index} 行")
            for index, (y0, y1) in enumerate(pairs)
        ]
    }


def test_leaking_corner_of_next_question_figure_is_snipped():
    """图顶伸进上一题卡 6pt（题大部分在下）→ 底边界上移到图顶并留余量。"""
    doc = _doc_with_figure(400.0, 200.0, 402.0, 260.0)
    records = _records((1, 50.0, 206.0), (2, 206.0, 300.0))
    warnings: list[str] = []

    changed = avoid_figure_cuts(doc, records, _lines((180.0, 192.0)), warnings)

    assert changed == 1
    assert abs(records[0].segments[0].y1 - (200.0 - FIGURE_CLEARANCE)) < 1.0
    assert records[1].segments[0].y1 == 300.0  # 下一题不动
    assert len(warnings) == 1 and "第 1 题" in warnings[0]


def test_figure_mostly_inside_the_card_is_left_alone():
    """图大部分在本卡内（属于本题）→ 不动，否则会把本题插图推出卡外。

    实测对应用例：第 40 题，图 32.2pt 在界内、18.1pt 在界外，就该原样保留。
    """
    doc = _doc_with_figure(400.0, 100.0, 402.0, 160.0)
    records = _records((1, 50.0, 140.0), (2, 140.0, 300.0))
    warnings: list[str] = []

    assert avoid_figure_cuts(doc, records, _lines((80.0, 92.0)), warnings) == 0
    assert records[0].segments[0].y1 == 140.0
    assert warnings == []


def test_never_cuts_the_questions_own_last_line():
    """让开的落点会切到本题末行 → 不动。宁可留一角杂质，也不裁掉文字。"""
    doc = _doc_with_figure(400.0, 200.0, 402.0, 260.0)
    records = _records((1, 50.0, 206.0), (2, 206.0, 300.0))
    warnings: list[str] = []

    # 末行 y0=198 y1=212：行首在边界之内（206 之前），行尾却越过让开后的 199。
    assert avoid_figure_cuts(doc, records, _lines((198.0, 212.0)), warnings) == 0
    assert records[0].segments[0].y1 == 206.0
    assert warnings == []


def test_shift_beyond_max_is_not_applied():
    """位移超过上限 → 不是"被切进来一角"，交回人工。"""
    doc = _doc_with_figure(400.0, 100.0, 402.0, 500.0)
    records = _records((1, 50.0, 190.0), (2, 190.0, 600.0))
    warnings: list[str] = []

    assert FIGURE_SNAP_MAX_SHIFT < 90.0
    assert avoid_figure_cuts(doc, records, _lines((150.0, 162.0)), warnings) == 0
    assert records[0].segments[0].y1 == 190.0


def test_small_decorative_lines_are_not_obstacles():
    """太扁的横线是分隔线不是插图，不该被当成障碍。"""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.draw_rect(fitz.Rect(50.0, 200.0, 550.0, 201.5), color=(0, 0, 0), width=0.5)
    records = _records((1, 50.0, 206.0), (2, 206.0, 300.0))
    warnings: list[str] = []

    assert avoid_figure_cuts(doc, records, _lines((180.0, 192.0)), warnings) == 0
    assert records[0].segments[0].y1 == 206.0
