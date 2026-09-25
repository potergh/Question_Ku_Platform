"""上传接口的通道分发锁。

``POST /api/upload`` 是三个通道唯一的入口：通道白名单、只收 PDF、Job.job_type、
后台任务入口，全都在这一步决定。这些判断原本散在 upload 与 extract 两个路由的
四处 if/else 里，现在收进了 channels 注册表 —— 这份测试就是那个契约。

``runner_for`` 装成桩：真实现会把 asyncio 任务跑起来去调 MinerU（花钱）。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.config import settings
from app.models import Job, Source
from app.routers import upload as upload_router
from app.services.api_extract_adapter import (
    CHANNEL_API_EXTRACT,
    CHANNEL_LOCAL_OCR,
    CHANNEL_MINERU,
)
from app.services.channels import channel_label

PDF_BYTES = b"%PDF-1.4\n%%EOF\n"


async def _upload(
    client,
    monkeypatch,
    tmp_path,
    *,
    channel: str,
    filename: str = "doc1.pdf",
    role: str = "paper",
    content_type: str = "application/pdf",
):
    """发一次上传请求，返回 (响应, 派发记录)。

    派发记录形如 [通道, (source_id, file_path, job_id)]；runner_for 被调到时
    先记通道，任务真正执行时再记参数。
    """
    started: list = []

    def fake_runner_for(channel_name):
        started.append(channel_name)

        async def runner(*args):
            started.append(args)

        return runner

    monkeypatch.setattr(upload_router, "runner_for", fake_runner_for)
    # upload_dir 不跟着 client fixture 的 data_dir 走，不单独改会写进真实目录
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")

    resp = await client.post(
        "/api/upload",
        files={"file": (filename, PDF_BYTES, content_type)},
        data={"channel": channel, "role": role, "subject": "physics"},
    )
    if resp.status_code == 200:
        await asyncio.sleep(0)  # 让 create_task 排进来的协程跑完
    return resp, started


async def _latest(test_db) -> tuple[Source, Job | None]:
    async with test_db() as db:
        source = (await db.execute(select(Source))).scalars().one()
        jobs = (await db.execute(select(Job))).scalars().all()
    return source, (jobs[0] if jobs else None)


async def test_mineru_channel_creates_mineru_job(client, test_db, tmp_path, monkeypatch):
    resp, started = await _upload(client, monkeypatch, tmp_path, channel=CHANNEL_MINERU)
    assert resp.status_code == 200

    source, job = await _latest(test_db)
    assert source.extract_channel == CHANNEL_MINERU
    assert source.ocr_status == "pending"

    # Job 类型与派发通道都要跟着走，否则任务列表认不出、还会跑错通道
    assert job is not None
    assert job.job_type == CHANNEL_MINERU
    assert started[0] == CHANNEL_MINERU
    assert started[1] == (source.id, source.file_path, job.id)


async def test_api_extract_channel_still_uses_its_own_job_type(
    client, test_db, tmp_path, monkeypatch
):
    """回归护栏：收进注册表不能把既有通道的类型改掉。"""
    resp, started = await _upload(client, monkeypatch, tmp_path, channel=CHANNEL_API_EXTRACT)
    assert resp.status_code == 200

    _, job = await _latest(test_db)
    assert job.job_type == CHANNEL_API_EXTRACT
    assert started[0] == CHANNEL_API_EXTRACT


async def test_staged_channels_reject_non_pdf(client, test_db, tmp_path, monkeypatch):
    """MinerU 官方也收 doc/docx，但裁题卡依赖 PyMuPDF，所以下一步必须回到 PDF。"""
    resp, _ = await _upload(
        client, monkeypatch, tmp_path, channel=CHANNEL_MINERU, filename="doc1.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert resp.status_code == 400
    assert "只支持 PDF" in resp.json()["detail"]
    # 通道名从 CHANNEL_LABELS 取，不写死字符串：这条断言真正要守的是
    # "报错里点名了是哪个通道"，而文案是中英混排、改一次叫法就得来改测试。
    assert channel_label(CHANNEL_MINERU) in resp.json()["detail"]


async def test_local_ocr_still_accepts_office_files(client, test_db, tmp_path, monkeypatch):
    """本地通道支持多格式的既有行为不能被这次改动收紧。"""
    resp, _ = await _upload(
        client, monkeypatch, tmp_path, channel=CHANNEL_LOCAL_OCR, filename="doc1.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert resp.status_code == 200


async def test_answer_doc_is_rejected_on_mineru(client, test_db, tmp_path, monkeypatch):
    """答案文档只有大模型通道有消费方；MinerU 通道尚未实现第三答案源。"""
    resp, _ = await _upload(
        client, monkeypatch, tmp_path, channel=CHANNEL_MINERU, role="answer_doc"
    )
    assert resp.status_code == 400
    assert "答案文档只支持大模型识别通道" in resp.json()["detail"]


async def test_unknown_channel_is_rejected(client, test_db, tmp_path, monkeypatch):
    resp, _ = await _upload(client, monkeypatch, tmp_path, channel="nope")
    assert resp.status_code == 400
    assert "未知识别通道" in resp.json()["detail"]
