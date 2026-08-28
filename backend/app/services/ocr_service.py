"""OCR processing service — wraps OCRAdapter with Job tracking."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models import Source, Question, Job
from app.services.ocr_adapter import OCRAdapter

logger = logging.getLogger(__name__)

# Shared adapter instance (thread-safe for reading)
_adapter = OCRAdapter()


async def process_pdf_async(source_id: str, pdf_path: str, job_id: str):
    """Run OCR in background thread, update DB when done.

    Called via asyncio.create_task() after upload.
    """
    async with async_session_factory() as db:
        # Mark job as running
        job = await db.get(Job, job_id)
        if job:
            job.status = "running"
            job.started_at = datetime.now()
            await db.commit()

        try:
            # Run OCR in thread pool (it's CPU-bound)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: _adapter.process_pdf(
                    Path(pdf_path),
                    settings.ocr_output_dir,
                ),
            )

            # Update source
            source = await db.get(Source, source_id)
            if source:
                source.ocr_status = "done"
                source.ocr_result_path = str(result.output_dir)
                source.question_count = result.question_count
                source.review_count = sum(1 for q in result.questions if q.needs_review)

            # Create questions from OCR result
            for qd in result.questions:
                question = Question(
                    source_id=source_id,
                    source_question_id=qd.source_question_id,
                    question_number=qd.question_number,
                    question_type=qd.question_type,
                    subject=source.subject if source else None,
                    raw_ocr_content=qd.raw_ocr_content,
                    content=qd.content,
                    options=qd.options,
                    answer=qd.answer,
                    explanation=qd.explanation,
                    score=qd.score,
                    card_image_path=qd.card_image_path,
                    needs_review=qd.needs_review,
                    review_status="pending" if qd.needs_review else "approved",
                    ocr_confidence=qd.ocr_confidence,
                )
                db.add(question)

            # Mark job as success
            if job:
                job.status = "success"
                job.progress = 100.0
                job.finished_at = datetime.now()

            await db.commit()
            logger.info(f"OCR completed for source {source_id}: {result.question_count} questions")

        except Exception as e:
            logger.error(f"OCR failed for source {source_id}: {e}")
            # Update source status
            source = await db.get(Source, source_id)
            if source:
                source.ocr_status = "error"
            # Update job status
            job = await db.get(Job, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.finished_at = datetime.now()
            await db.commit()
