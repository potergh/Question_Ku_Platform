"""Pydantic schemas for Question."""

from datetime import datetime
from pydantic import BaseModel


class TagBrief(BaseModel):
    """Brief tag info embedded in question responses."""
    id: str
    name: str
    category: str
    color: str | None = None

    model_config = {"from_attributes": True}


class QuestionResponse(BaseModel):
    id: str
    source_id: str
    source_question_id: str
    question_number: int
    question_type: str | None
    subject: str | None
    difficulty: int | None
    grade: str | None
    content: str | None
    options: list | None
    answer: str | None
    explanation: str | None
    score: float | None
    card_image_path: str | None
    needs_review: bool
    review_status: str
    ocr_confidence: float | None
    is_deleted: bool
    tags: list[TagBrief] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class QuestionUpdate(BaseModel):
    content: str | None = None
    options: list | None = None
    answer: str | None = None
    explanation: str | None = None
    question_type: str | None = None
    difficulty: int | None = None
    grade: str | None = None
    subject: str | None = None


class QuestionListResponse(BaseModel):
    questions: list[QuestionResponse]
    total: int
