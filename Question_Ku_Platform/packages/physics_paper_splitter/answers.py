from __future__ import annotations

import re

import pymupdf as fitz

from .models import DocumentInspection

# 强锚点：题号 + 点号 + 分值括号，可在行内任意位置出现；
# 部分解析行含公式乱码，题号会被拼进长行深处，行首匹配会漏题。
STRONG_ANCHOR_RE = re.compile(
    r"(?:[（(]\s*多选\s*[）)])?\s*(\d{1,2})\s*[\.．、]\s*[（(]\s*\d+\s*分\s*[）)]?"
)
# 弱锚点：行首题号，不要求分值括号，兼容无分值的答案格式。
WEAK_ANCHOR_RE = re.compile(r"^\s*(?:[（(]\s*多选\s*[）)])?\s*(\d{1,2})\s*[\.．、]\s*(?=[（(【])")
SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十]+\s*、")
PAGE_FOOTER_RE = re.compile(r"第\s*\d+\s*页[（(]共\s*\d+\s*页[）)]")
# 答案标记本身。绝不能写成 r"【\s*答案\s*】\s*([^\n]*)":
#   \s* 会跨过换行，把紧随【答案】的下一行「【分析】…」整行当成答案
#   （实测第 20 题把解析首行写进了 answer 字段）；[^\n]* 又只取一行，
#   答案分多个小问时后面几问直接丢失（实测第 21 题只剩「（1）…」）。
ANSWER_MARKER_RE = re.compile(r"【\s*答案\s*】")
# 答案块里的其它标记。答案内容遇到任一标记即结束，不再向后吞。
BLOCK_MARKER_RE = re.compile(
    r"【\s*(?:答案|分析|解析|详解|解答|点评|思路|难度|命题立意)\s*】"
)
# 「见试题解答内容」「答案见解析」这类是**指路牌**，不是答案文本：真正的答案
# 在解析正文里，而正文已经由 analysis 字段完整保留，信息一点没丢。
# 留着它的危害是它会以「答案」的身份补位 —— answer_key_llm 那一路漏了这道题时
# （实测和平卷第 16 题就是），产物里看着有答案、实际是一句空话。
# 按「缺答案比错答案好」处理：置空后该题会走 needs_review，人工一眼看得出要补。
POINTER_ANSWER_RE = re.compile(
    r"^[（(]?\s*(?:见|详见|答案见|参考|参看)\s*(?:试题)?\s*(?:解答|解析|详解|答案)"
)


def collect_answer_pages(doc: fitz.Document, inspection: DocumentInspection) -> list[tuple[int, str]]:
    """返回 (页码, 文字) 列表；没有答案页时返回空列表。"""
    if inspection.answer_start_page is None:
        return []
    pages: list[tuple[int, str]] = []
    for page_index in range(inspection.answer_start_page - 1, len(doc)):
        text = doc[page_index].get_text("text", sort=True)
        text = PAGE_FOOTER_RE.sub("", text)
        pages.append((page_index + 1, text))
    return pages


def split_answer_blocks(pages: list[tuple[int, str]]) -> list[dict]:
    """按题号锚点切块；块可以跨页延续。

    强锚点（带分值括号）可在行内任意位置命中，锚点前的文字归入上一题；
    强锚点未命中时回退到行首弱锚点。
    """
    blocks: list[dict] = []
    current: dict | None = None
    for page_number, text in pages:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            strong = STRONG_ANCHOR_RE.search(line)
            weak = WEAK_ANCHOR_RE.match(line) if strong is None else None
            match = strong or weak
            if match:
                prefix = line[: match.start()].strip()
                if current is not None and prefix:
                    current["lines"].append(prefix)
                if current is not None:
                    blocks.append(current)
                current = {"number": int(match.group(1)), "page": page_number, "lines": []}
                # 锚点后的剩余部分通常是题干开头，不能丢弃。
                rest = line[match.end() :].strip()
                if rest:
                    current["lines"].append(rest)
                continue
            if current is None or SECTION_RE.match(line):
                continue
            current["lines"].append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def parse_answer_block(number: int, page: int, lines: list[str]) -> dict:
    """从答案块中拆出短答（选择题选项）与完整解析文字。

    答案 = 「【答案】」标记之后、到下一个【标记】之前的全部文字，可能是一行
    （选择题选项），也可能是多行（综合题各小问，如第 21 题的 (1)(2)）。
    标记后没有内容时答案留空——那通常意味着答案是图或表格，绝不能顺手把
    后面【分析】的文字当成答案。

    标记后写「见试题解答内容」这类**指路牌**时同样留空（见 POINTER_ANSWER_RE）：
    它不是答案，留在 answer 字段里只会在别的来源漏题时冒充答案。
    """
    body = "\n".join(lines).strip()

    answer: str | None = None
    marker = ANSWER_MARKER_RE.search(body)
    if marker:
        tail = body[marker.end() :]
        following = BLOCK_MARKER_RE.search(tail)
        segment = tail[: following.start()] if following else tail
        answer = segment.strip() or None
        if answer and POINTER_ANSWER_RE.match(answer):
            answer = None
    else:
        # 没有【答案】标记时，解析文字的「故选：X」是答案的唯一抓手。
        choice = re.search(r"故选[：:]\s*([A-D]{1,4})", body)
        if choice:
            answer = choice.group(1)

    analysis: str | None = body if body else None
    return {"number": number, "answer": answer, "analysis": analysis, "page": page}


def parse_answers(doc: fitz.Document, inspection: DocumentInspection) -> dict:
    """解析答案页并按题号关联，输出可直接合并进 questions.json 的结构。"""
    pages = collect_answer_pages(doc, inspection)
    blocks = split_answer_blocks(pages)
    questions: dict[int, dict] = {}
    duplicates: list[int] = []
    for block in blocks:
        parsed = parse_answer_block(block["number"], block["page"], block["lines"])
        if block["number"] in questions:
            duplicates.append(block["number"])
            continue
        questions[block["number"]] = parsed

    return {
        "schema_version": 2,
        "answer_start_page": inspection.answer_start_page,
        "block_count": len(blocks),
        "matched_numbers": sorted(questions),
        "duplicates": duplicates,
        "questions": questions,
    }
