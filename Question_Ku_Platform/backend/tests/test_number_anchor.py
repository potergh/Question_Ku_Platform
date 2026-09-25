"""题号锚点校正：LLM 把下一题的题号行划进上一题时，确定性前移。

实测动机（2026-09-13）：和平卷第 22 题，LLM 给出的区间起点是第 159 行
（「时，电流表示数为1.2A…」），把第 158 行（「22．（6 分）…都闭合」）划给了
第 21 题 —— 第 22 题题干因此从半句话开始。裁图与几何都没错，错的是模型的
行区间判断。题号是 PDF 里客观存在的文本，拿它当锚点做确定性校正，比再问
一次模型更可靠也更便宜。

自限三条（每条都有对应用例）：只前移不后移、位移不超过 ANCHOR_MAX_SHIFT、
题号必须全卷唯一（讲义的【例1】重复出现时整体跳过）。
"""

from __future__ import annotations

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from app.services.api_extract.boundary import align_starts_to_number_anchors
from physics_paper_splitter.lines import TextLine


def _lines(texts: list[str]) -> list[TextLine]:
    return [
        TextLine(
            line_id=index,
            page_index=0,
            y0=100.0 + index * 24.0,
            y1=112.0 + index * 24.0,
            x0=0.0,
            x1=595.0,
            text=text,
        )
        for index, text in enumerate(texts)
    ]


def _index(lines: list[TextLine]) -> dict[int, TextLine]:
    return {line.line_id: line for line in lines}


def test_question_head_misassigned_to_previous_is_pulled_back():
    """第 22 题的题号行被算进第 21 题 → 起点前移到题号行。"""
    lines = _lines(
        [
            "21．（7 分）为了让鱼缸内的热带鱼有一个适合的生活环境",
            "（2）额定电压下，加热棒每次工作的时间是多少分钟？",
            "22．（6 分）如图所示电路中，小灯泡L 标有“6V 6W”字样",
            "时，电流表示数为1.2A，这时小灯泡L 正常发光。求：",
            "23．（6 分）如图所示，是某学习小组同学设计的实验电路图。",
        ]
    )
    questions = [
        {"label": "21．", "start_line": 0, "end_line": 2},
        {"label": "22．", "start_line": 3, "end_line": 3},
        {"label": "23．", "start_line": 4, "end_line": 4},
    ]
    warnings: list[str] = []
    result = align_starts_to_number_anchors(questions, _index(lines), warnings)

    assert result[1]["start_line"] == 2
    assert result[0]["end_line"] == 1  # 上一题相应回退
    assert result[2]["start_line"] == 4  # 正确的不动
    assert len(warnings) == 1 and "22" in warnings[0]


def test_already_correct_spans_are_untouched():
    lines = _lines(["21．第一题", "（1）小问", "22．第二题"])
    questions = [
        {"label": "21．", "start_line": 0, "end_line": 1},
        {"label": "22．", "start_line": 2, "end_line": 2},
    ]
    warnings: list[str] = []
    result = align_starts_to_number_anchors(questions, _index(lines), warnings)
    assert [(q["start_line"], q["end_line"]) for q in result] == [(0, 1), (2, 2)]
    assert warnings == []


def test_shift_beyond_max_is_not_applied():
    """题号行离得太远 → 不自动动手，交回人工。"""
    from app.services.api_extract.boundary import ANCHOR_MAX_SHIFT

    lines = _lines(["1．", "填充A", "填充B", "填充C", "填充D", "2．正文"])
    questions = [
        {"label": "1．", "start_line": 0, "end_line": 4},
        {"label": "2．", "start_line": 5, "end_line": 5},
    ]
    assert ANCHOR_MAX_SHIFT < 5
    result = align_starts_to_number_anchors(questions, _index(lines), [])
    assert result[1]["start_line"] == 5


def test_duplicate_labels_are_skipped():
    """讲义的【例1】在多个板块重复出现，锚点不唯一 → 整体不动。"""
    lines = _lines(["【例1】题干", "解析", "【例1】另一板块的题", "解析"])
    questions = [
        {"label": "【例1】", "start_line": 0, "end_line": 1},
        {"label": "【例1】", "start_line": 2, "end_line": 3},
    ]
    result = align_starts_to_number_anchors(questions, _index(lines), [])
    assert [(q["start_line"], q["end_line"]) for q in result] == [(0, 1), (2, 3)]


def test_would_invert_previous_span_is_skipped():
    """前移会让上一题的区间倒挂 → 放弃这次校正，不留非法区间。"""
    lines = _lines(["21．题干", "22．下一题"])
    questions = [
        {"label": "21．", "start_line": 1, "end_line": 1},
        {"label": "22．", "start_line": 1, "end_line": 1},
    ]
    result = align_starts_to_number_anchors(questions, _index(lines), [])
    assert result[1]["start_line"] == 1
    assert result[0]["end_line"] == 1


def test_bracketed_label_number_matches():
    """「（多选）11．」的题号是 11，锚点要认得出来。"""
    lines = _lines(["（多选）11．题干", "续行", "（多选）12．下一题"])
    questions = [
        {"label": "（多选）11．", "start_line": 0, "end_line": 1},
        {"label": "（多选）12．", "start_line": 2, "end_line": 2},
    ]
    result = align_starts_to_number_anchors(questions, _index(lines), [])
    assert result[1]["start_line"] == 2
