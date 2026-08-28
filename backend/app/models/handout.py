"""Handout + HandoutItem models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Handout(Base):
    __tablename__ = "handouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_student: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"grade": "...", "weaknesses": "...", "focus_areas": "...", "notes": "..."}
    teaching_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/ready/exported
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"has_answer_section": bool, "has_knowledge_summary": bool}
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # Relationships
    items = relationship("HandoutItem", back_populates="handout", cascade="all, delete-orphan",
                         order_by="HandoutItem.order")


class HandoutItem(Base):
    __tablename__ = "handout_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    handout_id: Mapped[str] = mapped_column(String(36), ForeignKey("handouts.id"), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # question / knowledge_note / example / exercise / section_title
    question_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Snapshot of question content at the time of adding to handout.
    # Prevents original question edits from affecting historical handouts.
    question_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"content": "...", "options": [...], "answer": "...", "explanation": "..."}

    custom_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    show_answer: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    handout = relationship("Handout", back_populates="items")
