"""英语专属题型：section→type 推断 + 归一 + 入库降级。

覆盖《河西区英语一模》审阅发现的问题：完形/阅读被误判 multiple_choice、
完成句子/任务型阅读/综合填空被误判 fill_blank、书面表达被误判 short_answer。
"""

from pathlib import Path

from app.services.api_extract_adapter import ExtractItemData
from app.utils.question_types import (
    PASSAGE_TYPES,
    QUESTION_TYPE_MAP,
    SUBJECT_TYPE_CATALOG,
    infer_question_type_from_section,
    normalize_question_type,
)


def test_infer_from_english_sections():
    cases = {
        "一、听力理解": "listening",
        "二、单项填空": "grammar_choice",
        "三、完形填空": "cloze",
        "四、阅读理解": "reading",
        "六、完成句子": "sentence_completion",
        "七、任务型阅读": "task_reading",
        "八、综合填空": "use_of_english",
        "九、书面表达": "writing",
    }
    for section, expected in cases.items():
        assert infer_question_type_from_section(section) == expected, section


def test_infer_priority_task_reading_vs_reading():
    # 任务型阅读含「阅读」，必须先于「阅读理解」命中，不能被误判为 reading
    assert infer_question_type_from_section("七、任务型阅读") == "task_reading"
    # 单项填空含「填空」，不能被完形/综合填空规则误吞
    assert infer_question_type_from_section("二、单项填空") == "grammar_choice"
    assert infer_question_type_from_section("三、完形填空") == "cloze"
    assert infer_question_type_from_section("八、综合填空") == "use_of_english"


def test_infer_none_for_generic_sections():
    # 选择/填空题故意不映射（无法区分单/多选，不能冲掉视觉模型已判对的类型）
    for section in ("一、选择题", "二、填空题", "三、多选题", None, ""):
        assert infer_question_type_from_section(section) is None


def test_infer_dialogue_completion():
    # 补全对话/七选五/信息匹配 → dialogue_completion（不再回落 comprehensive）
    assert infer_question_type_from_section("五、补全对话") == "dialogue_completion"
    assert infer_question_type_from_section("六、七选五") == "dialogue_completion"
    assert infer_question_type_from_section("信息匹配") == "dialogue_completion"
    # comprehensive 是通用码，会被 section 推断覆盖；用户已手改则保留
    assert normalize_question_type("comprehensive", "五、补全对话") == "dialogue_completion"
    assert normalize_question_type("reading", "五、补全对话") == "reading"
    assert "dialogue_completion" in PASSAGE_TYPES


def test_infer_science_sections():
    # 理化生专属板块归位（这些常被视觉模型压成 comprehensive/fill_blank）
    assert infer_question_type_from_section("五、实验题") == "experiment"
    assert infer_question_type_from_section("六、计算题") == "calculation"
    assert infer_question_type_from_section("四、简答题") == "short_answer"
    assert infer_question_type_from_section("三、解答题") == "comprehensive"


def test_subject_catalog_is_subset_of_type_map():
    # 每个学科目录里的码都必须在 QUESTION_TYPE_MAP 里有中文显示名
    for subject, codes in SUBJECT_TYPE_CATALOG.items():
        for code in codes:
            assert code in QUESTION_TYPE_MAP, f"{subject}:{code} 不在 QUESTION_TYPE_MAP"


def test_normalize_overrides_generic_with_english_type():
    assert normalize_question_type("multiple_choice", "四、阅读理解") == "reading"
    assert normalize_question_type("fill_blank", "八、综合填空") == "use_of_english"
    assert normalize_question_type("short_answer", "九、书面表达") == "writing"
    assert normalize_question_type(None, "三、完形填空") == "cloze"


def test_normalize_preserves_user_picked_type():
    # 用户已手改成具体英语题型 → 不被 section 推断覆盖
    assert normalize_question_type("reading", "四、阅读理解") == "reading"
    assert normalize_question_type("cloze", "四、阅读理解") == "cloze"


def test_normalize_keeps_generic_when_no_english_section():
    assert normalize_question_type("single_choice", None) == "single_choice"
    assert normalize_question_type("single_choice", "一、选择题") == "single_choice"


def test_passage_types_membership():
    assert "reading" in PASSAGE_TYPES and "cloze" in PASSAGE_TYPES
    assert "single_choice" not in PASSAGE_TYPES


def _item(**kw) -> ExtractItemData:
    base = dict(qid=1, question_number=1, label="1．", options=[{"label": "A", "content": "x"}])
    base.update(kw)
    return ExtractItemData(**base)


def test_to_question_data_applies_english_inference():
    item = _item(question_type="multiple_choice", section="四、阅读理解")
    assert item.to_question_data(Path(".")).question_type == "reading"


def test_to_question_data_preserves_specific_type():
    item = _item(question_type="cloze", section="四、阅读理解")
    assert item.to_question_data(Path(".")).question_type == "cloze"
