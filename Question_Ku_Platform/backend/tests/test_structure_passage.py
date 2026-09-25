"""英语篇章题两级结构化的管线单测（M2）。

覆盖三处，全部英语门控、物理等学科零影响：
1. structure_system_prompt：非英语逐字不变（不含 sub_questions 追加规则），英语追加。
2. _clean_sub_questions / _parse_payload：把模型返回的小题数组归一、非法降级。
3. distribute_answers_into_subquestions：把「（1）B…（10）C」整组答案串按序号拆进各小题。
"""

from app.services.api_extract.prompts import (
    STRUCTURE_ENGLISH_APPENDIX,
    structure_system_prompt,
)
from app.services.api_extract.passage_answers import (
    distribute_answers_into_subquestions,
)
from app.services.api_extract.structure import StructuredItem, _clean_sub_questions, _parse_payload


def test_non_english_structure_prompt_unchanged():
    for subject in ("physics", "物理", "math", "chemistry", None, ""):
        prompt = structure_system_prompt(subject)
        assert "sub_questions" not in prompt
        assert not prompt.endswith(STRUCTURE_ENGLISH_APPENDIX)


def test_english_structure_prompt_appends_passage_rules():
    for subject in ("english", "英语", " English "):
        prompt = structure_system_prompt(subject)
        assert prompt.endswith(STRUCTURE_ENGLISH_APPENDIX)
        assert "sub_questions" in prompt and "共享材料正文" in prompt


def test_clean_sub_questions_normalizes_and_drops_junk():
    rows = [
        {"label": "（1）", "stem": "Q1", "options": {"A": "run", "B": "walk"}, "answer": "A"},
        {"label": "（2）", "options": [{"label": "A", "content": "x"}]},
        "垃圾",
        {},
        {"stem": "   "},
    ]
    subs = _clean_sub_questions(rows)
    assert len(subs) == 2
    assert subs[0]["options"] == [
        {"label": "A", "content": "run"}, {"label": "B", "content": "walk"}
    ]
    assert subs[0]["answer"] == "A"
    assert "answer" not in subs[1]  # 没有 answer 就不塞空键


def test_parse_payload_fills_sub_questions():
    item = StructuredItem(qid=1)
    _parse_payload(
        {
            "stem_md": "一篇材料……",
            "options": [],
            "type": "reading",
            "sub_questions": [{"label": "（1）", "stem": "Q", "options": [{"label": "A", "content": "z"}]}],
        },
        item,
    )
    assert item.stem_md == "一篇材料……"
    assert len(item.sub_questions) == 1
    assert item.sub_questions[0]["options"][0]["content"] == "z"


def test_distribute_blob_into_subquestions():
    class FakeItem:
        excluded = False
        answer = "（1）B\n（2）C\n（3）D"
        sub_questions = [
            {"label": "（1）", "stem": "a"},
            {"label": "（2）", "stem": "b"},
            {"label": "（3）", "stem": "c"},
        ]

    item = FakeItem()
    filled = distribute_answers_into_subquestions([item])
    assert filled == 3
    answers = [s.get("answer") for s in item.sub_questions]
    assert answers == ["B", "C", "D"]
    # 顶层整组串保留不清（作为篇章题的答案汇总，也保证答案覆盖率审计不误计缺答）。
    assert item.answer == "（1）B\n（2）C\n（3）D"


def test_distribute_positional_letters_into_subquestions():
    class FakeItem:
        excluded = False
        answer = "ACD"
        sub_questions = [
            {"label": "21.", "stem": "a"},
            {"label": "22.", "stem": "b"},
            {"label": "23.", "stem": "c"},
        ]

    item = FakeItem()
    filled = distribute_answers_into_subquestions([item])
    assert filled == 3
    assert [s.get("answer") for s in item.sub_questions] == ["A", "C", "D"]


def test_distribute_skips_when_answers_already_inline():
    class FakeItem:
        excluded = False
        answer = ""
        sub_questions = [
            {"label": "（1）", "answer": "A"},
            {"label": "（2）", "answer": "B"},
        ]

    item = FakeItem()
    assert distribute_answers_into_subquestions([item]) == 0
