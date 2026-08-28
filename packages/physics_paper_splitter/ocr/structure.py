from __future__ import annotations

import re


SCORE_RE = re.compile(r"[（(]\s*(\d+)\s*分\s*[）)]")
QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:[（(]多选[）)])?\s*\d+\s*(?:[\.．、]\s*)?(?:[（(]\s*\d+\s*分\s*[）)])?\s*"
)
OPTION_RE = re.compile(r"(?m)(?:^|\s)([A-D])\s*[\.\uff0e、]\s*")
# 备用：纯字母选项（无分隔符），仅在标准匹配失败时使用
OPTION_LOOSE_RE = re.compile(r"(?m)(?:^|\s)([A-D])\s+(?=\S)")


def infer_question_type(section_title: str | None) -> str:
    if not section_title:
        return "unknown"
    # 多选题
    if "多项选择" in section_title:
        return "multiple_choice"
    # 单选题（“选择题”“单项选择”“单选”均匹配）
    if "单项选择" in section_title or "选择题" in section_title:
        return "single_choice"
    # 填空题
    if "填空" in section_title:
        return "fill_blank"
    # 解答题 / 简答题 / 论述题 / 综合题
    if any(kw in section_title for kw in ("综合", "解答", "简答", "论述", "计算")):
        return "comprehensive"
    # 实验题
    if "实验" in section_title:
        return "experiment"
    return "unknown"


def _clean_ocr_text(text: str) -> str:
    """清理 OCR 文字中的常见噪声。"""
    # 合并连续空行为单个换行
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 移除行尾多余空格
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    # 移除替换字符前后的无意义换行（OCR 将一行拆成多行）
    text = re.sub(r"\ufffd\n", "\ufffd", text)
    return text.strip()


def parse_content(text: str) -> dict:
    text = _clean_ocr_text(text)
    score_match = SCORE_RE.search(text)
    body = QUESTION_PREFIX_RE.sub("", text, count=1).strip()

    # 先尝试严格匹配（带分隔符），失败则用宽松匹配
    matches = list(OPTION_RE.finditer(body))
    if not matches:
        matches = list(OPTION_LOOSE_RE.finditer(body))

    if not matches:
        return {"score": int(score_match.group(1)) if score_match else None, "stem": body, "options": {}}

    stem = body[: matches[0].start()].strip()
    options: dict[str, str | None] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[match.end() : end].strip()
        # 清理选项值中的换行噪声
        value = re.sub(r"\s*\n\s*", " ", value).strip()
        options[match.group(1)] = value or None
    return {
        "score": int(score_match.group(1)) if score_match else None,
        "stem": stem,
        "options": options,
    }
