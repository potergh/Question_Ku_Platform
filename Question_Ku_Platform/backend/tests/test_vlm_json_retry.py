"""call_vlm_json 的解析重试与回复修复。

背景一：call_vlm 只在超时/429/5xx 上重试，而「HTTP 200 却返回被截断的 JSON」
要到解析这一步才暴露。实测和平卷第 13 题的结构化回复在 options 数组中途断掉，
整题作废。端点是聚合网关、同一输入两次输出不同，重试能救回来。

背景二：第 13 题的**真实**根因不是截断，而是 ``Invalid \\escape``（模型把表格
加粗写成 ``\\*``）。修在 `repair_invalid_escapes`，重试救不了。

背景三（本文件第 3 组测试的由来）：上一版 `repair_invalid_escapes` 用逐字符
正则删反斜杠，连 ``\\\\approx`` 里第二个反斜杠一起删了 —— 合法 JSON 被改成
非法，和平卷第 29/30/38 页整页转写全挂、整份文档被孤儿页闸门阻断。核心不变量：
**合法 JSON 过一遍 repair 必须一个字节都不变**。
"""

from __future__ import annotations

import json

import pytest

from app.services.api_extract import vlm_client
from app.services.api_extract.vlm_client import VLMError, call_vlm_json, parse_json

CONFIG = {"model": "qwen-vl-max", "base_url": "https://example.invalid", "api_key": "k"}


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(vlm_client.asyncio, "sleep", fake_sleep)


async def test_retries_after_truncated_reply(monkeypatch):
    replies = iter(['{"stem_md": "被截断', '{"stem_md": "完整", "options": []}'])
    calls: list[dict] = []

    async def fake_call_vlm(config, **kwargs):
        calls.append(kwargs)
        return next(replies)

    monkeypatch.setattr(vlm_client, "call_vlm", fake_call_vlm)

    payload = await call_vlm_json(CONFIG, system="s", user_text="u")

    assert payload == {"stem_md": "完整", "options": []}
    assert len(calls) == 2, "第一次解析失败后必须再调一次"
    assert calls[0]["temperature"] == 0.0


async def test_raises_after_all_attempts(monkeypatch):
    calls: list[dict] = []

    async def fake_call_vlm(config, **kwargs):
        calls.append(kwargs)
        return "not json at all"

    monkeypatch.setattr(vlm_client, "call_vlm", fake_call_vlm)

    with pytest.raises(VLMError):
        await call_vlm_json(CONFIG, system="s", user_text="u")

    assert len(calls) == vlm_client.MAX_RETRIES + 1


# ── 非法转义修复（第 13 题 JSON 失败的真根因，重试救不了）────────────────
#
# 实测：和平卷第 13 题（电烤箱铭牌表格）连着重试三次都栽在同一字符上，
# finish_reason 是 stop（不是 length），报错是 Invalid \escape @ 字符 80 ——
# 模型把 markdown 的加粗星号写成了 \*。


def test_repairs_invalid_escape_from_markdown_bold():
    """模型把 markdown 加粗写成 \\*，JSON 直接抛 Invalid \\escape。

    修复是「去掉多余的反斜杠」，不是「补一个反斜杠」—— 所以 `**\\*\\*X**`
    变成 `****X**`（多两个星号，但 markdown 渲染仍是加粗），
    关键差别是**能解析了**，而不是整题作废。
    """
    raw = '{"stem_md": "| **\\*\\*牌电烤箱** | |", "options": []}'
    assert parse_json(raw) == {"stem_md": "| ****牌电烤箱** | |", "options": []}


def test_repairs_latex_style_escapes():
    raw = '{"stem_md": "密度是 \\_\\_ 的", "unit": "\\("}'
    assert parse_json(raw) == {"stem_md": "密度是 __ 的", "unit": "("}


def test_keeps_legal_escapes_intact():
    """合法转义（\\\\ / \\n / \\"）不能被误删 —— 删了就是改坏题目内容。"""
    raw = '{"stem_md": "第一行\\n第二行", "latex": "$\\\\frac{1}{3}$", "quote": "\\"x\\""}'
    parsed = parse_json(raw)

    assert parsed["stem_md"] == "第一行\n第二行"
    assert parsed["latex"] == "$\\frac{1}{3}$"
    assert parsed["quote"] == '"x"'


async def test_invalid_escape_is_fixed_without_retry(monkeypatch):
    calls: list[dict] = []

    async def fake_call_vlm(config, **kwargs):
        calls.append(kwargs)
        return '{"answer": "\\*重点\\*"}'

    monkeypatch.setattr(vlm_client, "call_vlm", fake_call_vlm)

    payload = await call_vlm_json(CONFIG, system="s", user_text="u")

    assert payload == {"answer": "*重点*"}
    assert len(calls) == 1, "能就地修好就不该浪费一次重试"


async def test_passes_explicit_max_tokens(monkeypatch):
    """显式给输出上限，不依赖端点默认值。"""
    calls: list[dict] = []

    async def fake_call_vlm(config, **kwargs):
        calls.append(kwargs)
        return "{}"

    monkeypatch.setattr(vlm_client, "call_vlm", fake_call_vlm)

    await call_vlm_json(CONFIG, system="s", user_text="u")

    assert calls[0]["max_tokens"] == vlm_client.DEFAULT_MAX_TOKENS


async def test_fenced_json_parses_without_retry(monkeypatch):
    calls: list[dict] = []

    async def fake_call_vlm(config, **kwargs):
        calls.append(kwargs)
        return '```json\n{"a": 1}\n```'

    monkeypatch.setattr(vlm_client, "call_vlm", fake_call_vlm)

    assert await call_vlm_json(CONFIG, system="s", user_text="u") == {"a": 1}
    assert len(calls) == 1


async def test_transport_error_is_not_retried_here(monkeypatch):
    """网络层已经重试过；这里再套一层会让失败慢三倍。"""
    calls: list[dict] = []

    async def fake_call_vlm(config, **kwargs):
        calls.append(kwargs)
        raise VLMError("视觉模型响应超时")

    monkeypatch.setattr(vlm_client, "call_vlm", fake_call_vlm)

    with pytest.raises(VLMError):
        await call_vlm_json(CONFIG, system="s", user_text="u")

    assert len(calls) == 1


# ── 回归：修复非法转义不能反过来改坏合法转义 ──────────────────────────────
#
# 和平卷第三次回归：第 29/30/36/38 页（扫描页整页转写）全部失败，4 页从行清单
# 里消失 → 审计当成「有图无文字」的纯图页 → 孤儿页 → 闸门阻断。
# 实测每页的原始回复都是 finish_reason=stop、约 1000 tokens、围栏闭合、剥掉
# 围栏后 json.loads 直接通过 —— 是本地修复函数把好 JSON 改坏了。

# 模型写 LaTeX 时会把反斜杠双写成 JSON 的 ``\\``。这些内容在旧实现里会被删掉
# 第二个反斜杠（因为 ``a`` / ``D`` / ``%`` 不在合法转义字符表里）。
_PAGE_WITH_LATEX = (
    "```json\n"
    "{\n"
    '  "lines": [\n'
    '    {"text": "t=\\\\frac{W}{P}=3500s\\\\approx58.3min。", "y_ratio": 0.104},\n'
    '    {"text": "$\\\\Delta F=F_{浮1}-F_{浮3}$", "y_ratio": 0.5},\n'
    '    {"text": "效率 $\\\\eta=1-20\\\\%$", "y_ratio": 0.9}\n'
    "  ]\n"
    "}\n"
    "```"
)


def test_keeps_double_backslash_before_non_escape_char():
    """``\\\\approx`` / ``\\\\Delta`` / ``\\\\%`` 必须原样保留。

    旧实现删掉第二个反斜杠后变成 ``\\a`` / ``\\D`` / ``\\%``，全是非法转义，
    整页转写作废。新实现按两字符一对消费合法转义，不会被后面的字符误导。
    """
    parsed = parse_json(_PAGE_WITH_LATEX)

    assert parsed["lines"][0]["text"] == "t=\\frac{W}{P}=3500s\\approx58.3min。"
    assert parsed["lines"][1]["text"] == "$\\Delta F=F_{浮1}-F_{浮3}$"
    assert parsed["lines"][2]["text"] == "效率 $\\eta=1-20\\%$"


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": "\\\\"}',  # 单个转义反斜杠
        '{"a": "\\\\frac{1}{3}"}',
        '{"a": "x\\ny"}',
        '{"a": "\\u4e2d\\u6587"}',
        '{"a": "\\"引号\\""}',
        '["\\\\Delta", {"b": "\\\\approx 3.14"}]',
        '{"a": "c:\\\\path\\\\to"}',
    ],
)
def test_repair_is_identity_on_valid_json(raw):
    """核心不变量：本来能解析的 JSON，过一遍 repair 必须一个字节都不变。

    这是「只能删非法转义」的直接推论 —— 合法 JSON 里每个反斜杠都起一个合法
    转义，没有可删的东西。旧实现破坏的正是这条不变量。
    """
    json.loads(raw)  # 前置条件：这批样例本身就是合法 JSON
    assert vlm_client.repair_invalid_escapes(raw) == raw


def test_repairs_broken_unicode_escape():
    """``\\u`` 后面不是 4 位十六进制（如 \\underline 的单反斜杠写法）仍是非法转义。

    丢掉反斜杠保住整段，比让整个回复解析失败强；代价是 LaTeX 命令少了反斜杠，
    属于已知局限（见 repair_invalid_escapes docstring）。
    """
    assert parse_json('{"cmd": "\\underline{x}"}') == {"cmd": "underline{x}"}
    assert parse_json('{"a": "\\u4e2d"}') == {"a": "中"}


def test_error_message_locates_the_failing_char():
    """报错要带出错位置 —— 只报前 300 字会看不出问题在 1800 字之后。"""
    body = ",".join('{"text": "%s"}' % ("甲" * 60) for _ in range(20))
    raw = '{"lines": [' + body  # 故意缺右括号

    with pytest.raises(VLMError) as excinfo:
        parse_json(raw)

    message = str(excinfo.value)
    assert "@字符" in message
    assert "附近:" in message
    position = int(message.split("@字符 ", 1)[1].split("，", 1)[0])
    assert position > 300, "出错点应当落在旧实现根本看不到的位置"
