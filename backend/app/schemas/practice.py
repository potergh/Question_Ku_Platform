"""Pydantic schemas for Practice."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel


class PracticeCreateRequest(BaseModel):
    title: str
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    from_basket: bool = True
    question_ids: list[str] | None = None
    clear_basket: bool = False


class PracticeUpdateRequest(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    page_config: dict | None = None


class PracticeBrief(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    status: str
    question_count: int = 0
    is_baseline: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class PracticeBlockOut(BaseModel):
    id: str
    block_type: str
    position: int
    content: Any = None
    style: dict | None = None


class PreviewRenderResponse(BaseModel):
    pages: int
    sha: str


class PracticeQuestionOut(BaseModel):
    id: str
    position: int
    source_question_id: str | None = None
    question_number: int | None = None
    question_type: str | None = None
    difficulty: int | None = None
    score: float | None = None
    content: str | None = None
    options: list | None = None
    is_modified: bool
    layout_config: dict | None = None
    rich_document: dict | None = None
    blocks: list[PracticeBlockOut] = []


class PracticeSectionOut(BaseModel):
    id: str
    title: str
    section_type: str
    position: int
    show_title: bool
    start_on_new_page: bool
    questions: list[PracticeQuestionOut]


class PracticeResponse(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    status: str
    question_count: int = 0
    is_baseline: bool = False
    created_at: datetime
    updated_at: datetime | None = None
    page_config: dict | None = None
    sections: list[PracticeSectionOut]


class PracticeListResponse(BaseModel):
    practices: list[PracticeBrief]
    total: int
