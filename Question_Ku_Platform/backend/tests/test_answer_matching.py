"""答案条目按编号归并的容错。

实测和平卷：模型把整段题干塞进 label（"14．（2 分）如图所示，此时天平的读数为"），
题侧 label 却是 "14．"。normalize_label 对不上，trailing_number 又因为尾部没有
数字而取不到 —— 26 题里 18 道匹配失败，只能退回 answer_key_regex 顺序配对，
而那一路会把「见试题解答内容」这种占位文字当成答案。
"""

from __future__ import annotations

from app.services.api_extract.answers import (
    leading_number,
    match_entries,
    trailing_number,
)


def test_leading_number_reads_stem_number():
    """题干被塞进 label 时，题号在开头。"""
    assert leading_number("14．（2 分）如图所示，此时天平的读数为") == 14
    assert leading_number("8．（3 分）如图所示的电路中") == 8


def test_leading_number_keeps_section_prefix():
    """（多选）11． 这类带板块前缀的题号也要认。"""
    assert leading_number("（多选）11．（3 分）如图所示，不正确的是") == 11


def test_leading_number_ignores_sub_questions():
    """(1) 这类小问不能被误认成第 1 题，否则整份答案全部错位。"""
    assert leading_number("（1）画出图1 中物体的受力分析图") is None
    assert trailing_number("（1）画出图1 中物体的受力分析图") is None


def test_trailing_number_unchanged():
    assert trailing_number("例12") == 12
    assert trailing_number("无编号") is None


def test_stem_style_labels_still_match_by_number():
    """label 是整段题干时，靠前导数字把答案归到正确的题上。"""
    labels = [(1, "14．", None), (2, "（多选）11．", None)]
    entries = [
        {"label": "14．（2 分）如图所示，此时天平的读数为", "answer": "6.2g"},
        {"label": "（多选）11．（3 分）如图所示，不正确的是", "answer": "BC"},
    ]

    matched, per_item, warnings = match_entries(labels, entries)

    assert matched[1]["answer"] == "6.2g"
    assert matched[2]["answer"] == "BC"
    assert not warnings


def test_row_marker_labels_do_not_match():
    """行号式 label 已在上游丢弃，即便漏进来也不能匹配到任何题。"""
    labels = [(1, "1．", None)]
    entries = [{"label": "#539", "answer": "A"}]

    matched, _per_item, warnings = match_entries(labels, entries)

    assert matched == {}
    assert warnings


def test_null_string_fields_are_dropped():
    """模型把 JSON 的 null 写成字符串时，不能当成答案或解析。"""
    from app.services.api_extract.answers import _rows_to_entries

    entries = _rows_to_entries(
        [
            {"label": "23．", "answer": "null", "explanation": "解析文字"},
            {"label": "24．", "answer": "None", "explanation": "undefined"},
            {"label": "25．", "answer": "", "explanation": "只有解析"},
            {"label": "26．", "answer": "   ", "explanation": None},
        ]
    )

    assert [entry["answer"] for entry in entries] == [None, None, None, None]
    assert entries[0]["explanation"] == "解析文字"
    assert entries[1]["explanation"] is None
    assert entries[2]["explanation"] == "只有解析"


def test_placeholder_answers_are_kept():
    """原文里真实存在的占位说明（见试题解答内容）不能被当成空值丢掉。"""
    from app.services.api_extract.answers import _rows_to_entries

    entries = _rows_to_entries([{"label": "16．", "answer": "见试题解答内容"}])

    assert entries[0]["answer"] == "见试题解答内容"
