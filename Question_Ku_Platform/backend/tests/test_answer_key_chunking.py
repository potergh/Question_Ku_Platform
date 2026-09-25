"""答案区过长时必须切片，不能一次全喂进去。

实测：答案区整段兜底后达 669 行（其中 14 页扫描件转写撑出来的），单次请求
直接超时，LLM 这条答案源形同虚设，只剩 answer_key_regex 顺序配对兜底 ——
而那一路 answers.py 自己就写着「板块重启时最易错配」。
"""

from __future__ import annotations

import math

import pytest

from app.services.api_extract import answers as answers_mod
from app.services.api_extract.answers import (
    ANSWER_KEY_CHUNK_LINES,
    ANSWER_KEY_CHUNK_OVERLAP,
    _dedupe_entries,
    parse_answer_key_region,
    resolve_answers,
)
from app.services.api_extract.boundary import BoundaryResult
from app.services.api_extract.vlm_client import VLMError
from physics_paper_splitter.lines import to_plain_text

from test_api_extract import _page_lines


def _boundary(line_ids) -> BoundaryResult:
    result = BoundaryResult()
    result.answer_key_line_ids = set(line_ids)
    return result


def _fake(monkeypatch, payload, calls: list):
    async def fake(config, *, system, user_text, image_paths=None, **kwargs):
        calls.append(user_text)
        value = payload(user_text) if callable(payload) else payload
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(answers_mod, "call_vlm_json", fake)


def test_overlap_is_smaller_than_chunk():
    assert 0 < ANSWER_KEY_CHUNK_OVERLAP < ANSWER_KEY_CHUNK_LINES


async def test_long_answer_key_is_split_into_chunks(monkeypatch):
    """超过阈值的答案区分片调用，否则单次请求必然超时。"""
    total = ANSWER_KEY_CHUNK_LINES * 3
    lines = _page_lines({0: [f"答案行 {i}" for i in range(total)]})
    calls: list[str] = []
    _fake(monkeypatch, {"answers": []}, calls)

    await parse_answer_key_region({"model": "x"}, lines, _boundary(range(1, total + 1)))

    # 切片按步长滑动，片数由步长（而非段长）决定。
    step = ANSWER_KEY_CHUNK_LINES - ANSWER_KEY_CHUNK_OVERLAP
    assert len(calls) == math.ceil(total / step)


async def test_chunks_overlap_so_a_question_is_never_split(monkeypatch):
    """相邻切片必须重叠。

    题号与其答案被切到两段会两头落空：前段模型只见题号、按提示词规则填 null；
    后段看不到题号、而提示词禁止补全题号，该题直接没有条目（实测红桥卷 Q23
    就是这样丢的答案）。这里用「第一段末尾的行也出现在第二段」作为可观测证据。
    """
    total = ANSWER_KEY_CHUNK_LINES * 2
    lines = _page_lines({0: [f"答案行 {i}" for i in range(total)]})
    calls: list[str] = []
    _fake(monkeypatch, {"answers": []}, calls)

    await parse_answer_key_region({"model": "x"}, lines, _boundary(range(1, total + 1)))

    tail = f"答案行 {ANSWER_KEY_CHUNK_LINES - 1}"
    assert tail in calls[0]
    assert tail in calls[1]


async def test_chunk_results_are_merged(monkeypatch):
    """每片的结果都要汇总，不能只留最后一片。"""
    total = ANSWER_KEY_CHUNK_LINES * 2 + 10
    lines = _page_lines({0: [f"答案行 {i}" for i in range(total)]})
    seen: list[int] = []

    def payload(user_text: str):
        seen.append(len(seen))
        return {"answers": [{"label": str(len(seen)), "answer": "A"}]}

    _fake(monkeypatch, payload, [])

    entries = await parse_answer_key_region(
        {"model": "x"}, lines, _boundary(range(1, total + 1))
    )

    assert len(entries) == math.ceil(total / ANSWER_KEY_CHUNK_LINES)
    assert {entry["label"] for entry in entries} == {"1", "2", "3"}


async def test_one_chunk_failure_does_not_discard_the_rest(monkeypatch):
    """单段超时只丢该段，不该让整份答案区归零。"""
    total = ANSWER_KEY_CHUNK_LINES * 2
    lines = _page_lines({0: [f"答案行 {i}" for i in range(total)]})
    attempts: list[int] = []

    def payload(user_text: str):
        attempts.append(len(attempts))
        if len(attempts) == 1:
            return VLMError("视觉模型响应超时")
        return {"answers": [{"label": "2", "answer": "B"}]}

    _fake(monkeypatch, payload, [])

    entries = await parse_answer_key_region(
        {"model": "x"}, lines, _boundary(range(1, total + 1))
    )

    assert len(entries) == 1
    assert entries[0]["label"] == "2"


async def test_short_answer_key_is_single_unnumbered_call(monkeypatch):
    """没超阈值就保持原样：一次调用，origin 不带段号。"""
    lines = _page_lines({0: ["1．A", "2．B"]})
    calls: list[str] = []
    _fake(monkeypatch, {"answers": []}, calls)

    await parse_answer_key_region({"model": "x"}, lines, _boundary(range(1, 3)))

    assert len(calls) == 1
    assert "第 1/1 段" not in calls[0]


async def test_empty_answer_key_makes_no_request(monkeypatch):
    calls: list[str] = []
    _fake(monkeypatch, {"answers": []}, calls)

    entries = await parse_answer_key_region({"model": "x"}, [], _boundary([]))

    assert entries == []
    assert calls == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])


def test_row_marker_labels_are_dropped():
    """模型把「#539」行号前缀当题号时，这些条目必须丢弃。

    实测 247 条里 218 条是这种垃圾，它们撑爆匹配池，真答案反而排不上。
    """
    rows = [
        {"label": "#539", "answer": "A"},
        {"label": "#540 [p14 y=120]", "answer": "B"},
        {"label": "3．", "answer": "C"},
    ]

    entries = answers_mod._rows_to_entries(rows)

    assert [entry["label"] for entry in entries] == ["3．"]


async def test_answer_key_uses_plain_text_without_line_markers(monkeypatch):
    """答案区 prompt 不能带行号前缀 —— 那个前缀正是模型误认题号的源头。"""
    lines = _page_lines({0: ["1．A", "2．B"]})
    calls: list[str] = []
    _fake(monkeypatch, {"answers": []}, calls)

    await parse_answer_key_region({"model": "x"}, lines, _boundary(range(1, 3)))

    assert "#1 [p" not in calls[0]
    assert "1．A" in calls[0]


def test_to_plain_text_has_no_coordinates():
    lines = _page_lines({0: ["第一行", "第二行"]})
    assert to_plain_text(lines) == "第一行\n第二行"


# ── 重叠切片的副作用与题号配对 ────────────────────────────────────────


def test_dedupe_drops_overlap_repeats_but_keeps_real_duplicates():
    entries = [
        {"label": "23", "answer": "A", "explanation": None},
        {"label": "23", "answer": "A", "explanation": None},  # 重叠切片产生的同一份
        {"label": "23", "answer": "B", "explanation": None},  # 板块重启，真条目
    ]
    assert _dedupe_entries(entries) == [entries[0], entries[2]]


def test_pointer_only_entry_is_reported_per_item():
    """答案区只有编号、原文写「见试题解答内容」时，必须留下可读的原因。

    以前是静默 continue，用户只看到答案为空却不知道为什么。
    """
    results, warnings = resolve_answers(
        [(23, "23．（6 分）", "四、综合题")],
        [],
        inline_texts={},
        answer_key_llm=[{"label": "23", "answer": None, "explanation": None}],
    )

    assert results[0].answer is None
    assert results[0].needs_review is True
    assert "没有可抄写的答案" in (results[0].note or "")
    assert any("没有可抄写的答案" in w for w in warnings)


def test_scored_label_still_pairs_by_number():
    """题目 label 形如「23．（6 分）」：trailing_number 取不到数字，靠 leading_number 兜住。

    修之前这一路来源整条失效，还被报成「题号对应多道题」（实测红桥卷 15 条）。
    """
    results, warnings = resolve_answers(
        [(23, "23．（6 分）", "四、综合题")],
        [],
        inline_texts={},
        answer_key_regex={23: {"answer": "36V", "analysis": "欧姆定律"}},
    )

    assert results[0].answer == "36V"
    assert results[0].origin == "answer_key_regex"
    assert not any("没能与题目自动配对" in w for w in warnings)


def test_restart_numbering_is_reported_as_clash():
    """板块重启（同一整数对应多题）才该报「对应多道题」。"""
    results, warnings = resolve_answers(
        [(23, "23．（6 分）", "一、选择题"), (30, "23．（9 分）", "四、综合题")],
        [],
        inline_texts={},
        answer_key_regex={23: {"answer": "36V", "analysis": "欧姆定律"}},
    )

    assert all(result.answer is None for result in results)
    assert any("对应多道题" in w for w in warnings)
