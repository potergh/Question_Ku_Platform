"""Job model — tracks async tasks (OCR, AI, export)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Job(Base):
    """Tracks async tasks. On startup, running jobs with dead process → failed."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)  # ocr/ai_generate/export
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # queued / running / success / failed / cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)  # Cancellation flag
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    source = relationship("Source", foreign_keys=[source_id], primaryjoin="Job.source_id == Source.id")
