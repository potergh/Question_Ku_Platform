"""大模型用量记账（token）。

为什么要单独一层：调用方此前只取 ``choices[0].message.content``，把响应里的
``usage`` 整个丢掉了，于是「这一卷花了多少 token」无从回答——全仓库没有任何
记账代码，只能靠事后估。这里把 usage 累加到一个随任务走的账本上，由
api_extract_service 在任务结束时写进 extract.json，前端即可显示。

**并发正确性（关键）**：账本放在 ContextVar 里，但只改对象字段、绝不重新 set。
asyncio 创建任务时复制的是上下文**映射**而非对象，因此子任务里
``_CURRENT.get()`` 拿到的仍是同一个账本对象，累加能回传到父任务——
structure_questions 并发 3 的用量不会丢。同时每个识别任务在
``process_pdf_async`` 里各自 set 一次，任务之间互不串账。
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class UsageLedger:
    """一次识别任务的模型用量。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # 模型名 -> 调用次数：设置页里模型可改，记账要能看出来换成了哪个。
    by_model: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "by_model": dict(self.by_model),
        }


_CURRENT: contextvars.ContextVar[UsageLedger | None] = contextvars.ContextVar(
    "vlm_usage_ledger", default=None
)


@contextmanager
def track_usage() -> Iterator[UsageLedger]:
    """统计 with 块内所有 ``call_vlm`` 的用量。"""
    ledger = UsageLedger()
    token = _CURRENT.set(ledger)
    try:
        yield ledger
    finally:
        _CURRENT.reset(token)


def record_call(model: str | None, usage: dict | None) -> None:
    """记一次调用。端点没返回 usage 时只记次数，不编造 token 数。"""
    ledger = _CURRENT.get()
    if ledger is None:
        return

    name = model or "unknown"
    ledger.calls += 1
    ledger.by_model[name] = ledger.by_model.get(name, 0) + 1

    if not isinstance(usage, dict):
        return
    for key in ("prompt_tokens", "completion_tokens"):
        value = usage.get(key)
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            setattr(ledger, key, getattr(ledger, key) + amount)
