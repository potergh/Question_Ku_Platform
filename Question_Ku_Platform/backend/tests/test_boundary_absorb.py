"""英语边界补覆盖（boundary.absorb_uncovered_gap_lines）单测。

这条函数只对英语通道调用（调用点在 detect_boundaries 内用 is_english_subject 门控）。
函数只把 line_index 当"行是否存在"的成员映射用，不读文字，因此测试用 None 占位即可。
"""

from app.services.api_extract.boundary import absorb_uncovered_gap_lines


def _lines(upto):
    return {i: None for i in range(upto)}


def test_gap_between_two_questions_absorbed_into_preceding():
    line_index = _lines(10)
    questions = [
        {"label": "2．", "start_line": 1, "end_line": 1},   # 只框住题号行
        {"label": "3．", "start_line": 6, "end_line": 6},
    ]
    absorbed = absorb_uncovered_gap_lines(line_index, questions, [], [])
    # 第 2 题把 2..5 并回来，end_line 扩到下一题起点前一行(5)。
    assert questions[0]["end_line"] == 5
    assert absorbed == 4


def test_never_crosses_region_start():
    line_index = _lines(12)
    questions = [{"label": "2．", "start_line": 1, "end_line": 1}]
    regions = [{"start_line": 4, "end_line": 8, "kind": "section_header"}]
    absorb_uncovered_gap_lines(line_index, questions, regions, [])
    # 只能并到板块标题(4)之前，绝不吞掉标题行。
    assert questions[0]["end_line"] == 3


def test_last_question_not_extended_without_floor():
    line_index = _lines(10)
    questions = [{"label": "44．", "start_line": 1, "end_line": 1}]
    # 其后没有任何区间、也没答案区下限 → 不扩（宁缺勿滥）。
    absorbed = absorb_uncovered_gap_lines(line_index, questions, [], [])
    assert questions[0]["end_line"] == 1
    assert absorbed == 0


def test_answer_floor_stops_absorb_before_answer_area():
    line_index = _lines(20)
    questions = [{"label": "44．", "start_line": 1, "end_line": 1}]
    absorbed = absorb_uncovered_gap_lines(
        line_index, questions, [], [], answer_floor_line=10
    )
    # 扩到答案区起点前一行(9)，不越界进答案区。
    assert questions[0]["end_line"] == 9
    assert absorbed == 8


def test_max_absorb_caps_runaway_gap():
    line_index = _lines(100)
    questions = [{"label": "2．", "start_line": 1, "end_line": 1}]
    absorb_uncovered_gap_lines(
        line_index, questions, [], [], answer_floor_line=90, max_absorb=5
    )
    assert questions[0]["end_line"] == 6  # 只并前 5 行
