"""大模型用量记账。

重点锁两件事：并发子任务里的累加必须回传到主账本（structure_questions
并发 3，用 copy_context 的浅拷贝语义才成立）；端点没返回 usage 时只记次数。
"""

import asyncio

from app.services.api_extract.usage import record_call, track_usage


def test_record_without_ledger_is_noop():
    # 离线脚本、测试直接调用 call_vlm 时没有账本，不能抛异常。
    record_call("qwen-vl-max", {"prompt_tokens": 10, "completion_tokens": 1})


def test_accumulates_across_calls():
    with track_usage() as ledger:
        record_call("qwen-vl-max", {"prompt_tokens": 100, "completion_tokens": 20})
        record_call("qwen-vl-max", {"prompt_tokens": 50, "completion_tokens": 5})

    assert ledger.calls == 2
    assert ledger.prompt_tokens == 150
    assert ledger.completion_tokens == 25
    assert ledger.total_tokens == 175
    assert ledger.by_model == {"qwen-vl-max": 2}
    assert ledger.to_dict()["total_tokens"] == 175


def test_missing_usage_counts_only_calls():
    with track_usage() as ledger:
        record_call("m", None)
        record_call("m", {"prompt_tokens": "not-a-number"})

    assert ledger.calls == 2
    assert ledger.total_tokens == 0


async def _call_later(delay: float) -> None:
    await asyncio.sleep(delay)
    record_call("m", {"prompt_tokens": 10, "completion_tokens": 1})


def test_usage_from_concurrent_tasks_is_kept():
    """逐题结构化是 asyncio 并发跑的，用量不能因为任务边界而丢。"""

    async def main():
        with track_usage() as ledger:
            await asyncio.gather(*(_call_later(i * 0.01) for i in range(5)))
        return ledger

    ledger = asyncio.run(main())
    assert ledger.calls == 5
    assert ledger.prompt_tokens == 50
    assert ledger.completion_tokens == 5


def test_ledgers_do_not_leak_between_tasks():
    """两个识别任务各自 set 账本，互不串账。"""

    async def worker(tokens: int):
        with track_usage() as ledger:
            await asyncio.sleep(0.01)
            record_call("m", {"prompt_tokens": tokens})
        return ledger

    async def main():
        return await asyncio.gather(worker(1), worker(1000))

    first, second = asyncio.run(main())
    assert first.prompt_tokens == 1
    assert second.prompt_tokens == 1000
