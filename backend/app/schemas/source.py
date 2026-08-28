"""Pydantic schemas for Source (uploaded exam papers)."""

from datetime import datetime
from pydantic import BaseModel


class SourceCreate(BaseModel):
    filename: str
    file_type: str
    subject: str | None = None


class SourceResponse(BaseModel):
    id: str
    filename: str
    file_path: str
    file_type: str
    subject: str | None
    ocr_status: str
    question_count: int
    review_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    sources: list[SourceResponse]
    total: int
