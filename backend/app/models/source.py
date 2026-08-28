"""Source model — represents an uploaded exam paper."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf/word/ppt/latex/txt
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ocr_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/processing/done/error
    ocr_result_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    questions = relationship("Question", back_populates="source", cascade="all, delete-orphan")
