"""AI 求解：回复解析与失败退化。

不打真实接口 —— 这里锁的是「模型回复怎么被吃下」：
围栏 JSON、裸 JSON、完全不是 JSON 三种情况都要有确定行为。
"""

import pytest

from app.services import ai_service


async def test_parses_fenced_json(monkeypatch):
    async def fake_call(db, messages, temperature=None, timeout=60):
        return '好的：\n```json\n{"answer": "36V", "explanation": "由 $U=IR$ 得"}\n```'

    monkeypatch.setattr(ai_service, "_call_llm", fake_call)

    out = await ai_service.solve_question(
        None, content="求电源电压", options=[{"label": "A", "content": "36V"}], subject="physics"
    )

    assert out == {"answer": "36V", "explanation": "由 $U=IR$ 得"}


async def test_parses_bare_json_with_surrounding_text(monkeypatch):
    async def fake_call(db, messages, temperature=None, timeout=60):
        return '答案如下 {"answer": "ABD", "explanation": null} 以上。'

    monkeypatch.setattr(ai_service, "_call_llm", fake_call)

    out = await ai_service.solve_question(None, content="多选题")

    assert out["answer"] == "ABD"
    assert out["explanation"] is None


async def test_non_json_reply_degrades_to_explanation(monkeypatch):
    """模型没按格式回时不能丢内容：整段当解析给用户看。"""

    async def fake_call(db, messages, temperature=None, timeout=60):
        return "（1）电源电压为 36V；（2）R2 的阻值为 40Ω。"

    monkeypatch.setattr(ai_service, "_call_llm", fake_call)

    out = await ai_service.solve_question(None, content="计算题")

    assert out["answer"] is None
    assert "36V" in out["explanation"]


async def test_prompt_includes_options_and_existing_answer(monkeypatch):
    """已有答案要作为对照提示带进提示词，避免它与解析自相矛盾还无人察觉。"""
    seen: dict = {}

    async def fake_call(db, messages, temperature=None, timeout=60):
        seen["user"] = messages[-1]["content"]
        return '{"answer": "A", "explanation": "x"}'

    monkeypatch.setattr(ai_service, "_call_llm", fake_call)

    await ai_service.solve_question(
        None,
        content="下列说法正确的是",
        options=[{"label": "A", "content": "甲"}, {"label": "B", "content": "乙"}],
        subject="physics",
        answer="B",
    )

    assert "A. 甲" in seen["user"]
    assert "B. 乙" in seen["user"]
    assert "B" in seen["user"]


def test_parse_json_block_handles_garbage():
    assert ai_service._parse_json_block("") is None
    assert ai_service._parse_json_block("没有 JSON") is None
    assert ai_service._parse_json_block("[1, 2]") is None  # 数组不是我们要的结构


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
