"""Upload router — file upload, recognition trigger, source listing, asset serving."""

import asyncio
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Body
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Source, Job
from app.schemas.source import SourceResponse, SourceListResponse
from app.schemas.job import JobResponse
from app.services.api_extract_adapter import (
    CHANNEL_API_EXTRACT,
    CHANNEL_LOCAL_OCR,
    CHANNEL_MINERU,
    STAGED_CHANNELS,
)
from app.services.channels import channel_label, job_type_for, runner_for
from app.utils.assets import resolve_asset_urls, resolve_card_image_path

router = APIRouter()

SOURCE_ROLES = {"paper", "answer_doc"}
EXTRACT_CHANNELS = {CHANNEL_LOCAL_OCR, CHANNEL_API_EXTRACT, CHANNEL_MINERU}
# 走暂存区的通道只吃 PDF：裁题卡与抽插图依赖 PyMuPDF。MinerU 官方虽然也收
# doc/docx，但下一步的裁剪必须回到 PDF 上做，所以一并限制。
PDF_ONLY_TYPES = {".pdf"}


@router.post("/api/upload", response_model=SourceResponse)
async def upload_file(
    file: UploadFile = File(...),
    subject: str = Form(default=None),
    channel: str = Form(default=CHANNEL_LOCAL_OCR),
    role: str = Form(default="paper"),
    companion_filename: str = Form(default=None),
    doc_kind: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file and dispatch it to the recognition channel of choice.

    channel: local_ocr（默认，本地几何切题）/ api_extract（大模型判边界）
    role: paper（普通试卷/讲义）/ answer_doc（配套答案文档，不产出题目）
    companion_filename: role=paper 时可选，指定已上传的答案文档文件名
    doc_kind: 可选，提示文档形态（paper/lecture），缺省由模型自行判断
    """
    # Validate file type
    allowed_types = {".pdf", ".docx", ".pptx", ".txt"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_types:
        raise HTTPException(400, f"Unsupported file type: {file_ext}")

    if channel not in EXTRACT_CHANNELS:
        # 报错必须把「本服务认识哪些通道」一并说出来。界面加了新通道、而后端还是
        # 改动前启动的旧进程时，原样只回一句"未知识别通道：mineru"会把人引去查代码
        # （代码里明明有这个值），真正的原因却是服务没重启 —— 实测就这么绕了一圈。
        raise HTTPException(
            400,
            f"未知识别通道：{channel}。本服务认识的通道："
            f"{'、'.join(sorted(EXTRACT_CHANNELS))}。"
            f"如果界面上的通道比这里多，说明后端是改动前启动的旧进程，重启服务即可。",
        )
    if role not in SOURCE_ROLES:
        raise HTTPException(400, f"未知文档角色：{role}")
    if role == "answer_doc" and channel != CHANNEL_API_EXTRACT:
        # 答案文档只作为第三答案源被试卷任务代跑，其它通道没有这个消费方。
        raise HTTPException(400, "答案文档只支持大模型识别通道")
    if channel in STAGED_CHANNELS and file_ext not in PDF_ONLY_TYPES:
        raise HTTPException(
            400,
            f"{channel_label(channel)}暂只支持 PDF（裁题卡与抽插图依赖 PyMuPDF），"
            f"收到 {file_ext}",
        )

    # Check for duplicate file (same filename)
    existing = await db.execute(
        select(Source).where(Source.filename == file.filename)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"文件 '{file.filename}' 已上传过，请勿重复上传")

    # 配对答案文档必须在本次上传之前已入库，否则 spec 无法挂上第三答案源。
    companion: Source | None = None
    if companion_filename:
        found = await db.execute(
            select(Source).where(
                Source.filename == companion_filename,
                Source.role == "answer_doc",
            )
        )
        companion = found.scalar_one_or_none()
        if companion is None:
            raise HTTPException(
                400,
                f"找不到配对的答案文档 '{companion_filename}'："
                f"请先上传该文件，并确认其角色已设为「配套答案文档」",
            )

    # Save file
    file_id = str(uuid.uuid4())[:8]
    safe_name = f"{file_id}_{file.filename}"
    file_path = settings.upload_dir / safe_name
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Create source record
    source = Source(
        filename=file.filename,
        file_path=str(file_path),
        file_type=file_ext.lstrip("."),
        subject=subject,
        ocr_status="pending",
        role=role,
        extract_channel=channel,
        companion_source_id=companion.id if companion else None,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    # role=answer_doc 不单独跑任务：它的 items 由试卷任务顺手跑一遍当第三答案源。
    if role != "answer_doc" and file_ext == ".pdf":
        payload = {
            "channel": channel,
            "subject": subject,
            "doc_kind": doc_kind,
            "companion_source_id": companion.id if companion else None,
            "companion_filename": companion_filename,
        }
        job = Job(
            job_type=job_type_for(channel),
            source_id=source.id,
            status="queued",
            payload=json.dumps(payload, ensure_ascii=False),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Trigger recognition in background
        asyncio.create_task(
            runner_for(channel)(source.id, str(file_path), job.id)
        )

    return source


@router.get("/api/sources", response_model=SourceListResponse)
async def list_sources(
    status: str | None = Query(default=None, description="Filter by ocr_status"),
    include_answer_docs: bool = Query(
        default=False, description="是否包含 role=answer_doc 的配套答案文档"
    ),
    db: AsyncSession = Depends(get_db),
):
    """List all uploaded sources."""
    query = select(Source).order_by(Source.created_at.desc())
    if status:
        query = query.where(Source.ocr_status == status)
    if not include_answer_docs:
        # 答案文档不产出题目，默认不出现在「上传与识别」列表里。
        query = query.where(Source.role != "answer_doc")
    result = await db.execute(query)
    sources = result.scalars().all()
    return SourceListResponse(sources=sources, total=len(sources))


@router.get("/api/sources/subjects")
async def list_subjects(db: AsyncSession = Depends(get_db)):
    """Get distinct subjects from successful sources."""
    result = await db.execute(
        select(Source.subject)
        .where(Source.ocr_status == "done", Source.subject.isnot(None))
        .distinct()
    )
    subjects = [row[0] for row in result.all() if row[0]]
    return {"subjects": subjects}


@router.get("/api/sources/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single source by ID."""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.delete("/api/sources/{source_id}")
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a source, its questions, and OCR output files."""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    
    # Delete OCR output files if they exist
    if source.ocr_result_path:
        import shutil
        ocr_dir = Path(source.ocr_result_path)
        if ocr_dir.exists():
            shutil.rmtree(ocr_dir, ignore_errors=True)
    
    # Delete uploaded file
    upload_file = Path(source.file_path)
    if upload_file.exists():
        upload_file.unlink(missing_ok=True)
    
    await db.delete(source)
    await db.commit()
    return {"ok": True}


@router.post("/api/sources/batch-delete")
async def batch_delete_sources(
    source_ids: list[str] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple sources and their files."""
    import shutil
    count = 0
    for sid in source_ids:
        source = await db.get(Source, sid)
        if not source:
            continue
        # Delete OCR output
        if source.ocr_result_path:
            ocr_dir = Path(source.ocr_result_path)
            if ocr_dir.exists():
                shutil.rmtree(ocr_dir, ignore_errors=True)
        # Delete uploaded file
        upload_file = Path(source.file_path)
        if upload_file.exists():
            upload_file.unlink(missing_ok=True)
        await db.delete(source)
        count += 1
    await db.commit()
    return {"ok": True, "count": count}


@router.post("/api/jobs/clear-failed")
async def clear_failed_jobs(db: AsyncSession = Depends(get_db)):
    """Clear all failed/completed jobs from the queue."""
    from sqlalchemy import delete as sa_delete
    result = await db.execute(
        sa_delete(Job).where(Job.status.in_(["failed", "success"]))
    )
    await db.commit()
    return {"ok": True, "cleared": result.rowcount}


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Request cancellation of a running job."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    
    if job.status not in ("queued", "running"):
        raise HTTPException(400, "只能取消排队中或处理中的任务")
    
    job.cancelled = True
    if job.status == "queued":
        job.status = "failed"
        job.error_message = "用户取消"
        job.finished_at = datetime.now()
        
        # Also update source status
        if job.source_id:
            source = await db.get(Source, job.source_id)
            if source:
                source.ocr_status = "error"
    
    await db.commit()
    return {"ok": True, "status": "cancelled" if job.status == "running" else "failed"}


@router.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """删除单条任务记录（识别队列里的「删除」）。

    进行中的任务按「取消并删除」处理：只删行、不额外置 cancelled ——
    recognition_lifecycle.is_cancelled 把「任务行不存在」也算作取消，
    所以运行中的任务会在下一个检查点停下，并把 Source 标为失败。
    不这么做的话它会继续跑到底、把 Source 推进「待确认」，
    而用户以为自己已经把它删掉了 —— 凭空多出一份识别产物。
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    was_active = job.status in ("queued", "running")

    if was_active and job.source_id:
        # 就地把来源状态收干净。任务行删掉之后只剩「用户还看得见的那份状态」，
        # 不在这里改的话来源会一直停在「处理中」，直到用户手动刷新才发现任务没了。
        source = await db.get(Source, job.source_id)
        if source and source.ocr_status in ("pending", "processing"):
            source.ocr_status = "error"

    await db.delete(job)
    await db.commit()
    return {"ok": True, "was_active": was_active}


@router.get("/api/jobs", response_model=list[JobResponse])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """List all jobs (OCR, AI, export) with source info."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Job).options(selectinload(Job.source)).order_by(Job.created_at.desc()).limit(50)
    )
    jobs = result.scalars().all()
    response = []
    for j in jobs:
        data = JobResponse.model_validate(j)
        if j.source:
            data.filename = j.source.filename
            data.ocr_status = j.source.ocr_status
        response.append(data)
    return response


@router.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single job by ID."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/api/sources/{source_id}/retry")
async def retry_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Retry recognition for a failed source, on the channel it was uploaded with."""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if source.role == "answer_doc":
        raise HTTPException(400, "答案文档不单独重跑，请重试与其配对的试卷")
    if source.ocr_status not in ("error", "pending"):
        raise HTTPException(400, "只能重试失败的任务")

    channel = source.extract_channel or CHANNEL_LOCAL_OCR

    # Reset source status
    source.ocr_status = "pending"
    source.question_count = 0
    source.review_count = 0

    # 沿用上一条任务的 payload（doc_kind、配对信息），否则重跑会丢掉这些提示。
    last = await db.execute(
        select(Job)
        .where(Job.source_id == source.id)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    previous = last.scalar_one_or_none()
    payload = previous.payload if previous and previous.payload else None

    # Create new job
    job = Job(
        job_type=job_type_for(channel),
        source_id=source.id,
        status="queued",
        payload=payload,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Trigger recognition in background
    asyncio.create_task(runner_for(channel)(source.id, source.file_path, job.id))

    return {"ok": True, "job_id": job.id, "channel": channel}


# ── OCR Asset serving ────────────────────────────────────────────────


@router.get("/api/ocr-assets/{source_id}/{path:path}")
async def serve_ocr_asset(source_id: str, path: str, db: AsyncSession = Depends(get_db)):
    """Serve OCR output files (figures, card images) by source_id + relative path."""
    source = await db.get(Source, source_id)
    if not source or not source.ocr_result_path:
        raise HTTPException(404, "Source or OCR output not found")

    doc_dir = Path(source.ocr_result_path)
    if not doc_dir.exists():
        raise HTTPException(404, "OCR output directory not found")

    # Normalize double figures/figures/ → figures/ (for old buggy data)
    normalized_path = re.sub(r'^figures/figures/', 'figures/', path)

    # Try exact path first, then normalized path
    file_path = doc_dir / path
    if not file_path.exists():
        file_path = doc_dir / normalized_path
    if not file_path.exists():
        raise HTTPException(404, f"Asset not found: {path}")

    # Security: ensure the resolved path is within the doc_dir
    try:
        file_path.resolve().relative_to(doc_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")

    return FileResponse(str(file_path))
