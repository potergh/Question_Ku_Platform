"""各条识别通道共享的 Job / Source 生命周期骨架。

`ocr_service`（本地 OCR）与 `api_extract_service`（大模型）此前各自手写
"置 running → 查取消 → 进度 → 成功/失败/取消收尾" 的重复代码，取消分支
甚至在 ocr_service 里内联了四遍。此处收敛为共享原语，控制流仍留在各通道
（两者的进度区间、落库目标差异是真实差异，不做强行统一）。

`map_progress_band` 也放在这里：MinerU 通道要在 api_extract 管线外面再套一层
自己的进度区间（MinerU 阶段 + 管线阶段），若各通道自带一份，改一处忘一处
只会表现成进度条突然倒退。
"""

import json
import logging
from datetime import datetime

from app.models import Job, Source

logger = logging.getLogger(__name__)


def parse_job_payload(raw: str | None) -> dict:
    """读 Job.payload 里的通道参数（doc_kind、配对信息等）。

    payload 是自由 JSON，历史数据可能写坏 —— 坏数据只当没传，不该让任务崩掉。
    各通道共用同一份实现，免得「哪些字段能容错」在不同通道里答得不一样。
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("job payload 不是合法 JSON，已忽略：%r", raw)
        return {}
    return data if isinstance(data, dict) else {}

# 识别管线的进度值域：run_extract 从 5（running）推进到 95（审计）。
PIPELINE_PROGRESS_LOW = 5.0
PIPELINE_PROGRESS_SPAN = 90.0


def map_progress_band(emit, low: float, high: float, prefix: str = ""):
    """把管线的 5..95 进度线性映射到 [low, high] 再交给 emit。

    返回一个 async 回调，可直接当作 run_extract 的 progress 参数。
    """

    async def inner(value: float, stage: str | None = None) -> None:
        span = max(high - low, 0.0)
        mapped = low + (float(value) - PIPELINE_PROGRESS_LOW) * span / PIPELINE_PROGRESS_SPAN
        label = f"{prefix}{stage}" if stage else (prefix or None)
        await emit(min(max(mapped, low), high), label)

    return inner


async def mark_running(
    db,
    source_id: str,
    job_id: str,
    *,
    progress: float = 5.0,
    channel: str | None = None,
) -> None:
    """置 Job=running、Source=processing（可选同时写入识别通道）。"""
    job = await db.get(Job, job_id)
    if job:
        job.status = "running"
        job.started_at = datetime.now()
        job.progress = progress
    source = await db.get(Source, source_id)
    if source:
        source.ocr_status = "processing"
        if channel:
            source.extract_channel = channel
    await db.commit()


async def is_cancelled(db, job_id: str) -> bool:
    """该任务是否应当停下。

    两种情形都算：用户在任务列表点了「取消」（Job.cancelled），
    或者**任务行已经不存在**（用户把这条队列记录删了）。

    后者必须算作取消：行没了任务却继续跑的话，它会一路推进到 staging、
    把 Source 置成「待确认」，而用户以为自己已经把它删掉了 ——
    结果是凭空多出一份识别产物。
    """
    job = await db.get(Job, job_id)
    return job is None or bool(job.cancelled)


async def get_job(db, job_id: str) -> Job | None:
    """取（identity map 中的）Job，供需要读 payload 等字段的调用方使用。"""
    return await db.get(Job, job_id)


async def set_progress(db, job_id: str, value: float) -> None:
    job = await db.get(Job, job_id)
    if job:
        job.progress = float(value)
        await db.commit()


async def finish_cancelled(db, source_id: str, job_id: str) -> None:
    """取消等同失败，但错误信息可读（与 deleted/cancelled 的任务列表展示一致）。"""
    source = await db.get(Source, source_id)
    if source:
        source.ocr_status = "error"
    job = await db.get(Job, job_id)
    if job:
        job.status = "failed"
        job.error_message = "用户取消"
        job.finished_at = datetime.now()
    await db.commit()
    logger.info("识别任务已取消 source=%s", source_id)


async def finish_failed(db, source_id: str, job_id: str, message: str) -> None:
    source = await db.get(Source, source_id)
    if source:
        source.ocr_status = "error"
    job = await db.get(Job, job_id)
    if job:
        job.status = "failed"
        job.error_message = message
        job.finished_at = datetime.now()
    await db.commit()


async def finish_success(db, job_id: str, *, progress: float = 100.0) -> None:
    """只收尾 Job；Source 的终态由各通道自己写（done / staging 语义不同）。"""
    job = await db.get(Job, job_id)
    if job:
        job.status = "success"
        job.progress = progress
        job.finished_at = datetime.now()
