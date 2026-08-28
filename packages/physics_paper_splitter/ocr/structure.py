from __future__ import annotations

import re


SCORE_RE = re.compile(r"[（(]\s*(\d+)\s*分\s*[）)]")
QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:[（(]多选[）)])?\s*\d+\s*(?:[\.．、]\s*)?(?:[（(]\s*\d+\s*分\s*[）)])?\s*"
)
OPTION_RE = re.compile(r"(?m)(?:^|\s)([A-D])\s*[\.．、]\s*")


def infer_question_type(section_title: str | None) -> str:
    if not section_title:
        return "unknown"
    if "多项选择" in section_title:
        return "multiple_choice"
    if "单项选择" in section_title:
        return "single_choice"
    if "填空" in section_title:
        return "fill_blank"
    if "综合" in section_title:
        return "comprehensive"
    return "unknown"


def parse_content(text: str) -> dict:
    score_match = SCORE_RE.search(text)
    body = QUESTION_PREFIX_RE.sub("", text, count=1).strip()
    matches = list(OPTION_RE.finditer(body))
    if not matches:
        return {"score": int(score_match.group(1)) if score_match else None, "stem": body, "options": {}}

    stem = body[: matches[0].start()].strip()
    options: dict[str, str | None] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[match.end() : end].strip()
        options[match.group(1)] = value or None
    return {
        "score": int(score_match.group(1)) if score_match else None,
        "stem": stem,
        "options": options,
    }
