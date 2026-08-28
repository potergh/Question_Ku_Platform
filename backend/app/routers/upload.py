"""Upload router — file upload, OCR trigger, source listing, asset serving."""

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
from app.services.ocr_service import process_pdf_async

router = APIRouter()


@router.post("/api/upload", response_model=SourceResponse)
async def upload_file(
    file: UploadFile = File(...),
    subject: str = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF and trigger OCR processing."""
    # Validate file type
    allowed_types = {".pdf", ".docx", ".pptx", ".txt"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_types:
        raise HTTPException(400, f"Unsupported file type: {file_ext}")

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
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    # Create job for OCR
    if file_ext == ".pdf":
        job = Job(job_type="ocr", source_id=source.id, status="queued")
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Trigger OCR in background
        import asyncio
        asyncio.create_task(process_pdf_async(source.id, str(file_path), job.id))

    return source


@router.get("/api/sources", response_model=SourceListResponse)
async def list_sources(
    status: str | None = Query(default=None, description="Filter by ocr_status"),
    db: AsyncSession = Depends(get_db),
):
    """List all uploaded sources."""
    query = select(Source).order_by(Source.created_at.desc())
    if status:
        query = query.where(Source.ocr_status == status)
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
    """Retry OCR for a failed source."""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if source.ocr_status not in ("error", "pending"):
        raise HTTPException(400, "只能重试失败的任务")

    # Reset source status
    source.ocr_status = "pending"
    source.question_count = 0
    source.review_count = 0

    # Create new job
    job = Job(job_type="ocr", source_id=source.id, status="queued")
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Trigger OCR in background
    import asyncio
    asyncio.create_task(process_pdf_async(source.id, source.file_path, job.id))

    return {"ok": True, "job_id": job.id}


# ── OCR Asset serving ────────────────────────────────────────────────


def resolve_asset_urls(content: str | None, source_id: str) -> str | None:
    """Convert asset:// URLs to HTTP-servable /api/ocr-assets/{source_id}/... URLs.

    Handles:
    - asset://figures/figures/xxx.webp (old buggy double figures/)
    - asset://figures/xxx.webp (correct)
    - asset://questions/xxx.webp (card images)
    """
    if not content:
        return content

    def _replace(m):
        path = m.group(1)
        # Normalize double figures/figures/ → figures/
        path = re.sub(r'^figures/figures/', 'figures/', path)
        return f'/api/ocr-assets/{source_id}/{path}'

    return re.sub(r'asset://([^\s\)]+)', _replace, content)


def resolve_card_image_path(path: str | None, source_id: str) -> str | None:
    """Convert absolute filesystem card_image_path to HTTP URL."""
    if not path:
        return path
    # Extract relative path from the OCR output directory structure
    # e.g. D:\...\ocr_output\<doc>\questions\Q001.webp → questions/Q001.webp
    try:
        p = Path(path)
        # Find 'ocr_output' in the path parts and take everything after the doc dir
        parts = p.parts
        if 'ocr_output' in parts:
            idx = parts.index('ocr_output')
            # parts[idx] = 'ocr_output', parts[idx+1] = doc_dir, rest = relative path
            relative = '/'.join(parts[idx + 2:])
            return f'/api/ocr-assets/{source_id}/{relative}'
    except (ValueError, IndexError):
        pass
    return path


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
