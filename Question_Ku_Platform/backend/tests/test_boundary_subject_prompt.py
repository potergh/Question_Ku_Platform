"""边界判定 system prompt 的按学科隔离契约。

用户明确要求：「英语的方案不要影响之前的物理」。本测试把这条约束固化——
英语专属的篇章题整题成组/防漏规则只能追加到英语分支，物理等学科的基线必须逐字不变。
"""

from app.services.api_extract.prompts import (
    BOUNDARY_ENGLISH_APPENDIX,
    BOUNDARY_SYSTEM,
    boundary_system_prompt,
)


def test_base_prompt_has_no_english_passage_rules():
    # 基线（物理/数学/化学走的）绝不能混入英语拆题内容，否则等于污染他科。
    assert "篇章题整题成组" not in BOUNDARY_SYSTEM
    assert "cloze" not in BOUNDARY_SYSTEM
    assert "篇章题" not in BOUNDARY_SYSTEM


def test_non_english_subjects_get_byte_identical_baseline():
    for subject in ("physics", "math", "chemistry", "物理", None, "", "  "):
        assert boundary_system_prompt(subject) == BOUNDARY_SYSTEM


def test_english_subjects_append_passage_rules():
    for subject in ("english", "英语", "ENGLISH ", " English"):
        prompt = boundary_system_prompt(subject)
        # 以基线为前缀，追加段完整出现在末尾。
        assert prompt.startswith(BOUNDARY_SYSTEM)
        assert prompt.endswith(BOUNDARY_ENGLISH_APPENDIX)
        assert "篇章题整题成组" in prompt
        assert "cloze" in prompt and "reading" in prompt
        assert "绝不要把同一篇材料的小题拆成多条" in prompt


def test_english_prompt_differs_from_physics():
    assert boundary_system_prompt("english") != boundary_system_prompt("physics")
