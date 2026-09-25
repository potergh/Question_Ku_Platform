"""Source model — represents an uploaded exam paper."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)  # pdf/word/ppt/latex/txt
    # paper = 试卷/讲义本体；answer_doc = 配对的独立答案文档，不产出 Question。
    role: Mapped[str] = mapped_column(String(20), default="paper")
    # 识别通道：local_ocr = 本地几何切题；api_extract = 大模型识别。
    extract_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 指向配对的独立答案文档（第三答案源）。
    companion_source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ocr_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/processing/staging/done/error
    ocr_result_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    questions = relationship("Question", back_populates="source", cascade="all, delete-orphan")
    # 配对的答案文档；删除答案文档时本字段由 ON DELETE SET NULL 清空。
    companion_source = relationship("Source", remote_side="Source.id", foreign_keys=[companion_source_id])
