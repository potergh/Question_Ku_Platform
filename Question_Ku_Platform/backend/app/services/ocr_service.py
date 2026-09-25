"""OCR processing service — wraps OCRAdapter with Job tracking."""

import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.database import async_session_factory
from app.models import Source
from app.services.ocr_adapter import OCRAdapter
from app.services.question_builder import build_question
from app.utils.pdf_watermark import prepare_pdf
from app.services.recognition_lifecycle import (
    finish_cancelled,
    finish_failed,
    finish_success,
    is_cancelled,
    mark_running,
    set_progress,
)

logger = logging.getLogger(__name__)

# Shared adapter instance (thread-safe for reading)
_adapter = OCRAdapter()


async def process_pdf_async(source_id: str, pdf_path: str, job_id: str):
    """Run OCR in background thread, update DB when done.

    Called via asyncio.create_task() after upload.
    Supports cancellation via job.cancelled flag.
    """
    async with async_session_factory() as db:
        await mark_running(db, source_id, job_id, progress=5.0)

        try:
            # Check for cancellation before starting OCR
            if await is_cancelled(db, job_id):
                logger.info(f"OCR cancelled before start for source {source_id}")
                await finish_cancelled(db, source_id, job_id)
                return

            await set_progress(db, job_id, 10.0)

            # Run OCR in thread pool (it's CPU-bound)
            loop = asyncio.get_event_loop()
            # 先清掉自述水印：题卡与插图是对页面矩形直接光栅化，水印会一起被栅格化进图。
            # 要读写整份 PDF，同样丢进线程池，别占事件循环。
            pdf_for_ocr = await loop.run_in_executor(None, prepare_pdf, Path(pdf_path))
            result = await loop.run_in_executor(
                None,
                lambda: _adapter.process_pdf(
                    pdf_for_ocr,
                    settings.ocr_output_dir,
                ),
            )

            # Check for cancellation after OCR completes
            if await is_cancelled(db, job_id):
                logger.info(f"OCR cancelled after processing for source {source_id}")
                await finish_cancelled(db, source_id, job_id)
                return

            await set_progress(db, job_id, 70.0)

            # Update source
            source = await db.get(Source, source_id)
            if source:
                source.ocr_status = "done"
                source.ocr_result_path = str(result.output_dir)
                source.question_count = result.question_count
                source.review_count = sum(1 for q in result.questions if q.needs_review)

            # Create questions from OCR result
            for qd in result.questions:
                db.add(build_question(
                    qd,
                    source_id=source_id,
                    subject=source.subject if source else None,
                ))

            await set_progress(db, job_id, 90.0)
            await finish_success(db, job_id)
            await db.commit()
            logger.info(f"OCR completed for source {source_id}: {result.question_count} questions")

            # AI auto-tagging disabled during import — user must manually trigger AI tagging

        except Exception as e:
            logger.error(f"OCR failed for source {source_id}: {e}")
            await finish_failed(db, source_id, job_id, str(e))
