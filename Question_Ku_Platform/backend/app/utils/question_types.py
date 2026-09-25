"""Question type mapping — OCR English types to Chinese display names."""

# OCR pipeline returns English types; UI displays Chinese
QUESTION_TYPE_MAP = {
    "single_choice": "选择题",
    "multiple_choice": "多选题",
    "fill_blank": "填空题",
    "comprehensive": "综合题",
    "experiment": "实验题",
    "calculation": "计算题",
    "short_answer": "简答题",
    "essay": "论述题",
    "unknown": "未知题型",
    # 英语专属题型（中考/高考英语卷常见板块，理化卷不会出现这些码）
    "listening": "听力题",
    "grammar_choice": "单项填空",
    "cloze": "完形填空",
    "reading": "阅读理解",
    "task_reading": "任务型阅读",
    "use_of_english": "综合填空",
    "sentence_completion": "完成句子",
    "writing": "书面表达",
    # Chinese types (already correct)
    "选择题": "选择题",
    "多选题": "多选题",
    "填空题": "填空题",
    "解答题": "解答题",
    "实验题": "实验题",
    "计算题": "计算题",
    "简答题": "简答题",
    "论述题": "论述题",
    "综合题": "综合题",
}

# Subject mapping
SUBJECT_MAP = {
    "physics": "物理",
    "math": "数学",
    "chemistry": "化学",
    "english": "英语",
}

# 篇章题（一篇材料挂多个小题）：当前单题模型无法表达小题选项，
# 复核/详情页不再把「第一小题的一套选项」当整题选项展示（Phase 2 拆分小题后修正）。
PASSAGE_TYPES = {
    "cloze", "reading", "task_reading", "use_of_english",
    "sentence_completion", "writing",
}

# 理化通用题型码：这些可被 section 推断出的英语专属题型覆盖；
# 用户已手改成具体英语题型则不覆盖。
_GENERIC_TYPE_CODES = {
    "single_choice", "multiple_choice", "fill_blank", "comprehensive",
    "experiment", "calculation", "short_answer", "essay", "unknown",
    "选择题", "多选题", "填空题", "解答题", "实验题", "计算题",
    "简答题", "论述题", "综合题",
}

# 板块关键词 → 题型码。按顺序匹配（先特异后泛化）：
# “任务型阅读”必须先于“阅读理解”（都含“阅读”）；“单项/完形/综合填空”用完整词而非“填空”。
# 故意不映射“选择题”（无法区分单选/多选，会冲掉视觉模型已判对的 multiple_choice）。
_SECTION_TYPE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("任务型阅读",), "task_reading"),
    (("完形填空", "完形"), "cloze"),
    (("单项填空", "单项选择"), "grammar_choice"),
    (("综合填空", "短文填空", "语法填空", "词汇运用"), "use_of_english"),
    (("阅读理解", "阅读"), "reading"),
    (("完成句子", "翻译"), "sentence_completion"),
    (("书面表达", "作文"), "writing"),
    (("听力",), "listening"),
    # 理化生专属板块（英语规则已在上方命中，不会误入）：把常被压成 comprehensive 的题归位
    (("实验",), "experiment"),
    (("计算",), "calculation"),
    (("简答",), "short_answer"),
    (("解答", "综合题", "综合应用"), "comprehensive"),
]

# 学科→适用题型码（题库筛选与校验的单一真源，与前端 questionTypes.js 保持一致）
SUBJECT_TYPE_CATALOG: dict[str, list[str]] = {
    "physics": ["single_choice", "multiple_choice", "fill_blank", "experiment",
                "calculation", "comprehensive", "short_answer"],
    "math": ["single_choice", "multiple_choice", "fill_blank", "comprehensive"],
    "chemistry": ["single_choice", "multiple_choice", "fill_blank", "short_answer",
                  "experiment", "calculation", "comprehensive"],
    "english": ["listening", "grammar_choice", "cloze", "reading", "task_reading",
                "use_of_english", "sentence_completion", "writing"],
}


def infer_question_type_from_section(section: str | None) -> str | None:
    """从中文板块标题推断题型码；无命中返回 None。"""
    if not section:
        return None
    for keywords, code in _SECTION_TYPE_RULES:
        if any(kw in section for kw in keywords):
            return code
    return None


def normalize_question_type(question_type: str | None, section: str | None) -> str | None:
    """若现有题型是理化通用码且 section 能映射到英语题型，用推断结果覆盖。"""
    inferred = infer_question_type_from_section(section)
    if inferred and (not question_type or question_type in _GENERIC_TYPE_CODES):
        return inferred
    return question_type


def map_question_type(en_type: str | None) -> str:
    """Map OCR English question type to Chinese display name."""
    if not en_type:
        return "未知题型"
    return QUESTION_TYPE_MAP.get(en_type, en_type)


def map_subject(en_subject: str | None) -> str:
    """Map English subject to Chinese display name."""
    if not en_subject:
        return "-"
    return SUBJECT_MAP.get(en_subject, en_subject)
