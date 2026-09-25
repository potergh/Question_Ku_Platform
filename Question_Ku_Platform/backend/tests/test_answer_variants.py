"""答案详略变体：同一答案抄多抄少不算冲突，且取更完整的那版。

实测背景（2026-09-12 用户核对和平卷）：第 21 题 PDF 原文是
「（1）正常工作时，水吸收的热量是8.4×10⁵J；（2）额定电压下，加热棒每次工作
的时间是58.3min。」，LLM 那路抄成了「（1）8.4×10⁵J；（2）58.3min」，与
regex 那路（原文）互标冲突，最终还采用了摘要版。三个要求：prompt 要求逐字
抄写、详略差异不算冲突、答案字段取完整版。
"""

from __future__ import annotations

from app.services.api_extract.answers import (
    _compact_text,
    _is_abbreviation,
    resolve_answers,
)


def test_compact_normalizes_superscripts_and_punct():
    """PDF 文字层把 10⁵ 丢成 105、LLM 保留上标，归一后必须能对上。"""
    assert _compact_text("（1）8.4×10⁵J；（2）58.3min") == _compact_text(
        "1正常工作时，水吸收的热量是8.4×105J"[:0] + "（1）8.4×105J；（2）58.3min"
    )


def test_abbreviation_requires_margin():
    full = _compact_text(
        "（1）正常工作时，水吸收的热量是8.4×105J；\n（2）额定电压下，加热棒每次工作的时间是58.3min。"
    )
    brief = _compact_text("（1）8.4×10⁵J；（2）58.3min")
    assert _is_abbreviation(brief, full)
    # 长度接近的差异不是缩略 —— "ABD" vs "BD" 这种选择题漏字母是真冲突
    assert not _is_abbreviation("ABD", "BD")
    # 短串一律不参与（"C" 几乎是任何选项串的子序列）
    assert not _is_abbreviation("C", full)


FULL_21 = "（1）正常工作时，水吸收的热量是8.4×105J；\n（2）额定电压下，加热棒每次工作的时间是58.3min。"
BRIEF_21 = "（1）8.4×10⁵J；（2）58.3min"


def test_resolve_prefers_fuller_variant_and_skips_conflict():
    resolved, _ = resolve_answers(
        [(1, "21．", None)],
        [],
        inline_texts={},
        answer_key_llm=[{"label": "21．", "answer": BRIEF_21}],
        answer_key_regex={21: {"answer": FULL_21}},
    )
    result = resolved[0]
    assert result.answer.startswith("（1）正常工作时"), "取完整版，不取摘要"
    assert result.origin == "answer_key_regex"
    assert not result.conflict, "同一答案的详略差异不算冲突"


def test_resolve_keeps_priority_when_fuller_is_another_answer():
    """低优先级更长但不是缩略关系（内容真的不同）→ 维持优先级并标冲突。"""
    resolved, _ = resolve_answers(
        [(1, "8．", None)],
        [],
        inline_texts={},
        answer_key_llm=[{"label": "8．", "answer": "C"}],
        answer_key_regex={8: {"answer": "B"}},
    )
    result = resolved[0]
    assert result.answer == "C"
    assert result.conflict


def test_resolve_still_flags_true_conflict_with_similar_length():
    resolved, _ = resolve_answers(
        [(1, "11．", None)],
        [],
        inline_texts={},
        answer_key_llm=[{"label": "11．", "answer": "ABD"}],
        answer_key_regex={11: {"answer": "BD"}},
    )
    assert resolved[0].answer == "ABD"
    assert resolved[0].conflict, "漏一个字母的『缩略』是漏选，必须标冲突"
