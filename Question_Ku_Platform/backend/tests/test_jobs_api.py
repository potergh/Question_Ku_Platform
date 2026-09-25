"""识别队列的单条删除。

三条语义必须锁住，每条漏了都会产生「用户以为删掉了、其实没删」的假象：

1. 删除是**硬删**：记录真的消失，不是打个标记（标记的话下次刷新又冒出来）；
2. 删**进行中**的任务 = 取消并删除：来源状态要就地从「处理中」收干净，
   否则它会一直停在处理中，直到用户手动刷新才发现任务早就没了；
3. **任务行不存在时 is_cancelled 返回 True** —— 这才是「删了就真的会停」
   的机制本身。改回 `bool(job and job.cancelled)` 的话，被删掉的任务会继续
   跑到最后，把来源推进「待确认」，凭空多出一份识别产物。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Job, Source
from app.services.api_extract_adapter import CHANNEL_API_EXTRACT
from app.services.recognition_lifecycle import is_cancelled


async def _seed(
    test_db,
    *,
    status: str = "success",
    cancelled: bool = False,
    ocr_status: str = "processing",
) -> tuple[str, str]:
    async with test_db() as db:
        source = Source(
            filename="a.pdf",
            file_path="/tmp/a.pdf",
            file_type="pdf",
            role="paper",
            ocr_status=ocr_status,
            extract_channel=CHANNEL_API_EXTRACT,
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)

        job = Job(
            job_type="ocr",
            source_id=source.id,
            status=status,
            cancelled=cancelled,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return source.id, job.id


async def _jobs(test_db) -> list[Job]:
    async with test_db() as db:
        return list((await db.execute(select(Job))).scalars().all())


async def test_delete_finished_job(client, test_db):
    _, job_id = await _seed(test_db, status="success")

    resp = await client.delete(f"/api/jobs/{job_id}")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "was_active": False}
    assert await _jobs(test_db) == []


async def test_delete_active_job_also_settles_source_status(client, test_db):
    source_id, job_id = await _seed(test_db, status="running", ocr_status="processing")

    resp = await client.delete(f"/api/jobs/{job_id}")

    assert resp.status_code == 200
    assert resp.json()["was_active"] is True
    assert await _jobs(test_db) == []
    async with test_db() as db:
        source = await db.get(Source, source_id)
    assert source.ocr_status == "error"


async def test_delete_job_does_not_touch_finished_source(client, test_db):
    """已经识别完成的来源不该被删任务连累。"""
    source_id, job_id = await _seed(test_db, status="queued", ocr_status="done")

    assert (await client.delete(f"/api/jobs/{job_id}")).status_code == 200

    async with test_db() as db:
        source = await db.get(Source, source_id)
    assert source.ocr_status == "done"


async def test_delete_missing_job_returns_404(client, test_db):
    resp = await client.delete("/api/jobs/nope")
    assert resp.status_code == 404


async def test_missing_job_counts_as_cancelled(test_db):
    """机制本身：任务行被删掉后，运行中的任务必须停下来。"""
    async with test_db() as db:
        assert await is_cancelled(db, "不存在的任务") is True

    _, job_id = await _seed(test_db, status="running", cancelled=False)
    async with test_db() as db:
        assert await is_cancelled(db, job_id) is False
