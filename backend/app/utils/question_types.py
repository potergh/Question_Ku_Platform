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
    "chinese": "语文",
    "biology": "生物",
    "history": "历史",
    "geography": "地理",
    "politics": "政治",
}


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
