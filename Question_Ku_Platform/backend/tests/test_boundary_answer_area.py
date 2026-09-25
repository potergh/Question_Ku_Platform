"""答案/解析区不能产出独立题目。

真实样本（2022 天津和平一模，38 页）实测：答案区把正文 26 题整题重印一遍
并附上答案，边界判定会当成新题再切一次，26 题变成 52 题。剔除重印题的同时
必须保住该区域的 answer_key 区域 —— 正文那 26 题的答案全靠它归一。
"""

from __future__ import annotations

import pytest

from app.services.api_extract import boundary as boundary_mod
from app.services.api_extract.boundary import detect_boundaries

from test_api_extract import PAGE_HEIGHT, PAGE_WIDTH, _doc, _fake_vlm, _page_lines

# 页 0 是题目页，页 1 起是答案/解析区（标题行 + 重印题）。
_LINES = {
    0: ["1．第一题题干", "选项 A 内容", "选项 B 内容"],
    1: ["参考答案与试题解析", "1．第一题题干（重印）", "答案：A"],
}
# line_id：页 0 -> 1,2,3；页 1 -> 4,5,6
_ANSWER_HEAD_LINE = 4
_REPRINT_RANGE = (5, 6)


def _payload():
    return {
        "doc_kind": "paper",
        "questions": [
            {"label": "1", "type": "single_choice", "score": 3, "start_line": 1, "end_line": 3},
            {
                "label": "1",
                "type": "single_choice",
                "score": 3,
                "start_line": _REPRINT_RANGE[0],
                "end_line": _REPRINT_RANGE[1],
            },
        ],
        "non_question_regions": [
            {"start_line": _ANSWER_HEAD_LINE, "end_line": _ANSWER_HEAD_LINE, "kind": "answer_key"}
        ],
    }


async def test_reprinted_questions_in_answer_area_are_dropped(monkeypatch):
    """答案区重印的题必须剔除，只留正文那一份。"""
    _fake_vlm(monkeypatch, _payload())
    doc = _doc(2)
    lines = _page_lines(_LINES)

    result = await detect_boundaries({"model": "x"}, doc, lines, question_page_count=1)

    assert len(result.spans) == 1
    assert result.spans[0].start_line == 1


async def test_answer_area_becomes_answer_source_even_without_answer_key(monkeypatch):
    """剔除重印题不能把答案源一起删掉。

    实测模型会把答案区的重印题干判成 question、解析文字判成 other，一个
    answer_key 都不给，正文题就会全部拿不到答案。所以答案区整段兜底成答案源，
    不依赖模型把它判成 answer_key。
    """
    _fake_vlm(monkeypatch, _payload())
    doc = _doc(2)
    lines = _page_lines(_LINES)

    result = await detect_boundaries({"model": "x"}, doc, lines, question_page_count=1)

    assert {_ANSWER_HEAD_LINE, *_REPRINT_RANGE} <= result.answer_key_line_ids


async def test_dropped_reprint_lines_leave_the_coverage_denominator(monkeypatch):
    """重印题覆盖的行必须进 excluded，否则覆盖率被答案区拖垮。"""
    _fake_vlm(monkeypatch, _payload())
    doc = _doc(2)
    lines = _page_lines(_LINES)

    result = await detect_boundaries({"model": "x"}, doc, lines, question_page_count=1)

    assert {_ANSWER_HEAD_LINE, *_REPRINT_RANGE} <= result.excluded_line_ids


async def test_dropping_is_reported_in_warnings(monkeypatch):
    """剔除是静默丢内容，必须留下可见痕迹。"""
    _fake_vlm(monkeypatch, _payload())
    doc = _doc(2)
    lines = _page_lines(_LINES)

    result = await detect_boundaries({"model": "x"}, doc, lines, question_page_count=1)

    assert any("重印" in warning for warning in result.warnings)


async def test_without_question_page_count_nothing_is_dropped(monkeypatch):
    """没有题目页边界（答案行内的讲义）时行为不变。"""
    _fake_vlm(monkeypatch, _payload())
    doc = _doc(2)
    lines = _page_lines(_LINES)

    result = await detect_boundaries({"model": "x"}, doc, lines)

    assert len(result.spans) == 2


async def test_question_page_count_covering_whole_doc_drops_nothing(monkeypatch):
    """没有独立答案区时 inspector 返回总页数，等价于不截断。"""
    _fake_vlm(monkeypatch, _payload())
    doc = _doc(2)
    lines = _page_lines(_LINES)

    result = await detect_boundaries({"model": "x"}, doc, lines, question_page_count=2)

    assert len(result.spans) == 2
    assert not any("重印" in warning for warning in result.warnings)


def test_page_geometry_helpers_available():
    """守卫：这些常量/辅助若改名，上面的用例会直接报错而不是悄悄失效。"""
    assert PAGE_WIDTH > 0 and PAGE_HEIGHT > 0
    assert boundary_mod.detect_boundaries is detect_boundaries


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
