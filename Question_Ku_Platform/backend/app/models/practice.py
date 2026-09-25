"""Practice models — practice, sections, question snapshots, content blocks."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Practice(Base):
    __tablename__ = "practices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / exported
    page_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 阶段 5：整册编排布局（线性块序列：subtitle/question_ref/custom_text/spacer/page_break）。
    # 空/None = 未迁移，渲染走旧 sections；整册保存后为真源，sections 同步保持一致（架构 A 并存可回退）。
    layout_document: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 阶段 0 新文档结构迁移状态：pending（待迁移）/ done / failed / native（新建即用新结构）
    migration_status: Mapped[str] = mapped_column(String(20), default="pending")
    migration_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    migrated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 基线样本标记（用户决策 2026-08-30：留在列表但加标记，不隐藏）
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    sections = relationship(
        "PracticeSection", back_populates="practice",
        cascade="all, delete-orphan", order_by="PracticeSection.position",
    )


class PracticeSection(Base):
    __tablename__ = "practice_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    section_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 题型中文名或 "custom"
    position: Mapped[int] = mapped_column(Integer, default=0)
    show_title: Mapped[bool] = mapped_column(Boolean, default=True)
    start_on_new_page: Mapped[bool] = mapped_column(Boolean, default=False)

    practice = relationship("Practice", back_populates="sections")
    questions = relationship(
        "PracticeQuestion", back_populates="section",
        cascade="all, delete-orphan", order_by="PracticeQuestion.position",
    )


class PracticeQuestion(Base):
    """题目快照：加入练习时复制，编辑永不写回题库。"""

    __tablename__ = "practice_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    practice_id: Mapped[str] = mapped_column(String(36), ForeignKey("practices.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(36), ForeignKey("practice_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    # 不设外键：快照独立于题库，原题删除不影响练习
    source_question_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    question_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_version: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    layout_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 阶段 0 新富文本文档（Tiptap 风格 JSON 字符串）；0 = 未生成，1 = schema v1。
    # 旧字段 content_snapshot / options_snapshot 在迁移稳定前保留，支持回退读取。
    rich_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_version: Mapped[int] = mapped_column(Integer, default=0)

    section = relationship("PracticeSection", back_populates="questions")
    blocks = relationship(
        "PracticeContentBlock", back_populates="question",
        cascade="all, delete-orphan", order_by="PracticeContentBlock.position",
    )


class PracticeContentBlock(Base):
    """题内内容块（阶段二编辑器消费，阶段一仅建表）。"""

    __tablename__ = "practice_content_blocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    practice_question_id: Mapped[str] = mapped_column(String(36), ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)  # text/image/options/answer_space/answer/explanation
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    question = relationship("PracticeQuestion", back_populates="blocks")
