"""定向仲裁（arbitrate_conflicts）的行为测试。

约定：仲裁只对 conflict=True 且证据「真互斥」的题发起；三态结论只写进
note，不改 answer/origin/conflict；unclear 与调用失败都必须维持冲突标记。
裁判模型在测试里用 monkeypatch 替身，不发真实网络请求。
"""

from __future__ import annotations

import pytest

from app.services.api_extract import answers as answers_mod
from app.services.api_extract.answers import (
    AnswerEvidence,
    ResolvedAnswer,
    arbitrate_conflicts,
)


def _conflicted(qid: int = 1) -> ResolvedAnswer:
    return ResolvedAnswer(
        qid=qid,
        answer="A",
        origin="answer_key_llm",
        conflict=True,
        needs_review=True,
        note="多个答案来源不一致：answer_key_llm=A / answer_key_regex=B",
        evidences=[
            AnswerEvidence(
                origin="answer_key_llm", label="1", answer="A", explanation="语义路解析"
            ),
            AnswerEvidence(
                origin="answer_key_regex", label="1", answer="B", explanation="正则路解析"
            ),
        ],
    )


LABELS = [(1, "1．", None)]
INLINE_TEXTS = {1: "1．（2 分）下列说法正确的是\nA. 甲 B. 乙 C. 丙 D. 丁"}


@pytest.mark.asyncio
async def test_verdict_b_writes_note_but_keeps_answer(monkeypatch):
    """裁判采信 B：note 追加仲裁结论，answer/origin/conflict 原样保留。"""

    async def fake_call(config, *, system, user_text, image_paths=None):
        assert "证据 A" in user_text and "证据 B" in user_text
        return {"verdict": "B", "reason": "证据B与原文逐字一致"}

    monkeypatch.setattr(answers_mod, "call_vlm_json", fake_call)
    item = _conflicted()
    results, warnings = await arbitrate_conflicts({}, [item], LABELS, INLINE_TEXTS)

    assert len(results) == 1
    assert results[0].verdict == "B"
    assert results[0].adopted_origin == "answer_key_regex"
    assert item.answer == "A"
    assert item.origin == "answer_key_llm"
    assert item.conflict is True
    assert "仲裁：采信 answer_key_regex" in item.note
    assert any("定向仲裁" in w for w in warnings)


@pytest.mark.asyncio
async def test_unclear_verdict_keeps_conflict(monkeypatch):
    """裁判也拿不准：必须落回人工，冲突标记与 needs_review 不降级。"""

    async def fake_call(config, *, system, user_text, image_paths=None):
        return {"verdict": "unclear", "reason": "两路证据都找不到原文"}

    monkeypatch.setattr(answers_mod, "call_vlm_json", fake_call)
    item = _conflicted()
    results, _warnings = await arbitrate_conflicts({}, [item], LABELS, INLINE_TEXTS)

    assert results[0].verdict == "unclear"
    assert results[0].adopted_origin is None
    assert item.conflict is True
    assert "仲裁：无法裁定" in item.note


@pytest.mark.asyncio
async def test_vlm_failure_degrades_to_warning(monkeypatch):
    """裁判调用失败：冲突题原样保留，全局告警说明原因，不得抛异常。"""

    async def fake_call(config, *, system, user_text, image_paths=None):
        raise answers_mod.VLMError("429 rate limited")

    monkeypatch.setattr(answers_mod, "call_vlm_json", fake_call)
    item = _conflicted()
    results, warnings = await arbitrate_conflicts({}, [item], LABELS, INLINE_TEXTS)

    assert results == []
    assert "仲裁调用失败" in warnings[0]
    assert item.note.startswith("多个答案来源不一致")


@pytest.mark.asyncio
async def test_garbage_verdict_falls_back_to_unclear(monkeypatch):
    """裁判返回无法理解的结论：按 unclear 处理，不静默选边。"""

    async def fake_call(config, *, system, user_text, image_paths=None):
        return {"verdict": "C", "reason": ""}

    monkeypatch.setattr(answers_mod, "call_vlm_json", fake_call)
    item = _conflicted()
    results, _warnings = await arbitrate_conflicts({}, [item], LABELS, INLINE_TEXTS)

    assert results[0].verdict == "unclear"


@pytest.mark.asyncio
async def test_abbreviation_conflict_never_sent_to_judge(monkeypatch):
    """详略变体不算真冲突，不应发起仲裁调用。"""

    async def fail_call(config, *, system, user_text, image_paths=None):
        raise AssertionError("详略变体不应触发仲裁调用")

    monkeypatch.setattr(answers_mod, "call_vlm_json", fail_call)
    item = ResolvedAnswer(
        qid=1,
        answer="（1）8.4×105J",
        origin="answer_key_llm",
        conflict=True,
        evidences=[
            AnswerEvidence(origin="answer_key_llm", answer="（1）8.4×105J"),
            AnswerEvidence(
                origin="answer_key_regex", answer="（1）正常工作时，水吸收的热量是8.4×105J"
            ),
        ],
    )
    results, _warnings = await arbitrate_conflicts({}, [item], LABELS, INLINE_TEXTS)
    assert results == []


@pytest.mark.asyncio
async def test_non_conflict_items_are_skipped(monkeypatch):
    """无冲突的题不应触发任何裁判调用。"""

    async def fail_call(config, *, system, user_text, image_paths=None):
        raise AssertionError("无冲突不应触发仲裁调用")

    monkeypatch.setattr(answers_mod, "call_vlm_json", fail_call)
    clean = ResolvedAnswer(
        qid=1,
        answer="A",
        origin="inline",
        evidences=[AnswerEvidence(origin="inline", answer="A")],
    )
    results, _warnings = await arbitrate_conflicts({}, [clean], LABELS, INLINE_TEXTS)
    assert results == []
