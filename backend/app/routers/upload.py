"""Upload router — file upload, OCR trigger, source listing."""

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
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
async def list_sources(db: AsyncSession = Depends(get_db)):
    """List all uploaded sources."""
    result = await db.execute(select(Source).order_by(Source.created_at.desc()))
    sources = result.scalars().all()
    return SourceListResponse(sources=sources, total=len(sources))


@router.get("/api/sources/{source_id}", response_model=SourceResponse)
async def get_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single source by ID."""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


@router.delete("/api/sources/{source_id}")
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a source and all its questions."""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    await db.delete(source)
    await db.commit()
    return {"ok": True}


@router.get("/api/jobs", response_model=list[JobResponse])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """List all jobs (OCR, AI, export)."""
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(50))
    return result.scalars().all()


@router.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single job by ID."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
