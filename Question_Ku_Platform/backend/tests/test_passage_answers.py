"""篇章题小题答案拆分回填（passage_answers.distribute_group_answers）单测。

用真实 ExtractItemData 构造与 2023 河西英语实测同形的数据：整组答案挤在该组
第一个小题里、其余小题为空。验证：按 (k) 序号拆开各归各的、纯字母串按位分配、
没答案串的组不动、非小题不动。
"""

from app.services.api_extract.passage_answers import distribute_group_answers
from app.services.api_extract_adapter import ExtractItemData


def _item(qid, label, answer="", flags=None):
    return ExtractItemData(
        qid=qid, question_number=qid, label=label, answer=answer,
        audit_flags=list(flags or []),
    )


def test_marker_blob_split_across_subquestions():
    # 完形 32：整组「（1）B…（10）C」挤在 32．（1）里，其余空。
    items = [
        _item(1, "32．（1）", "（1）B\n（2）C\n（3）D", flags=[]),
        _item(2, "32．（2）", "", flags=["no_answer"]),
        _item(3, "32．（3）", "", flags=["no_answer"]),
    ]
    filled = distribute_group_answers(items)
    assert filled == 2
    assert items[0].answer == "B"
    assert items[1].answer == "C"
    assert items[2].answer == "D"
    # 回填后清掉 no_answer 标记。
    assert "no_answer" not in items[1].audit_flags


def test_reading_sentence_answers_split():
    items = [
        _item(1, "42．（1）", "（1）the first two paragraphs\n（2）only the first sentence"),
        _item(2, "42．（2）", "", flags=["no_answer"]),
    ]
    distribute_group_answers(items)
    assert items[0].answer == "the first two paragraphs"
    assert items[1].answer == "only the first sentence"


def test_positional_letter_blob_fallback():
    # 无 (k) 序号、答案是一串纯字母 ACDCB，且小题数=5 → 按位分配。
    items = [
        _item(1, "33．（1）", "ACDCB"),
        _item(2, "33．（2）", "", flags=["no_answer"]),
        _item(3, "33．（3）", "", flags=["no_answer"]),
        _item(4, "33．（4）", "", flags=["no_answer"]),
        _item(5, "33．（5）", "", flags=["no_answer"]),
    ]
    distribute_group_answers(items)
    assert [it.answer for it in items] == ["A", "C", "D", "C", "B"]


def test_group_without_answer_blob_is_left_untouched():
    items = [
        _item(1, "33．（1）", "", flags=["no_answer"]),
        _item(2, "33．（2）", "", flags=["no_answer"]),
    ]
    filled = distribute_group_answers(items)
    assert filled == 0
    assert items[0].answer == "" and items[1].answer == ""


def test_plain_single_questions_not_touched():
    # 单项填空「17．」无小问序号，不参与分组；即便有答案也不动。
    items = [
        _item(1, "17．", "B"),
        _item(2, "18．", "C"),
    ]
    filled = distribute_group_answers(items)
    assert filled == 0
    assert items[0].answer == "B" and items[1].answer == "C"


def test_single_member_group_skipped():
    # 某主编号只有一条带 (1) 的、没有兄弟小题 → 不拆。
    items = [_item(1, "44．（1）", "some long essay answer text")]
    filled = distribute_group_answers(items)
    assert filled == 0
    assert items[0].answer == "some long essay answer text"
