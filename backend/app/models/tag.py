"""Tag model — organized by subject + category (knowledge/skill/error_type/custom).

Tags are primarily grouped by subject (physics/math/chemistry/english),
then by category within each subject.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Many-to-many association table
question_tags = Table(
    "question_tags",
    Base.metadata,
    Column("question_id", String(36), ForeignKey("questions.id"), primary_key=True),
    Column("tag_id", String(36), ForeignKey("tags.id"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(20), nullable=True)  # physics/math/chemistry/english
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # knowledge/skill/error_type/custom
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tags.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    parent = relationship("Tag", remote_side=[id], backref="children")
    questions = relationship("Question", secondary=question_tags, back_populates="tags")
