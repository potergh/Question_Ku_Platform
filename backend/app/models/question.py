"""Question model — core entity. Markdown canonical content."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), nullable=False)
    source_question_id: Mapped[str] = mapped_column(String(100), nullable=False)  # OCR original ID
    question_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 选择题/填空题/解答题/...
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 高一/高三/...

    # Content — Markdown canonical
    raw_ocr_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # OCR original, NEVER overwritten
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # Markdown with inline images + LaTeX
    options: Mapped[list | None] = mapped_column(JSON, default=list)  # [{"label":"A","content":"..."}]
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    card_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Review
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/edited
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # AI suggestions (populated after OCR if AI is enabled)
    # {"tag_ids": [...], "difficulty": 3, "question_type": "...", "confidence": 0.8}
    ai_suggestions: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationships
    source = relationship("Source", back_populates="questions", foreign_keys=[source_id])
    tags = relationship("Tag", secondary="question_tags", back_populates="questions")
