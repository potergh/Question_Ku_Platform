"""Pydantic schemas for Question."""

from datetime import datetime
from pydantic import BaseModel, model_validator, Field

from app.routers.upload import resolve_asset_urls, resolve_card_image_path
from app.utils.question_types import QUESTION_TYPE_MAP


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
    question_type_zh: str | None = Field(default=None, description="Chinese question type")
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
    ai_suggestions: dict | None = None
    tags: list[TagBrief] = []
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode='after')
    def transform_asset_urls(self):
        """Convert asset:// URLs and absolute paths to HTTP-servable URLs."""
        if self.source_id:
            if self.content and 'asset://' in self.content:
                self.content = resolve_asset_urls(self.content, self.source_id)
            if self.card_image_path and ('\\' in (self.card_image_path or '') or self.card_image_path.startswith('/')):
                self.card_image_path = resolve_card_image_path(self.card_image_path, self.source_id)
            # Also resolve asset:// URLs in options
            if self.options and isinstance(self.options, list):
                for opt in self.options:
                    if isinstance(opt, dict) and opt.get('content') and 'asset://' in str(opt['content']):
                        opt['content'] = resolve_asset_urls(opt['content'], self.source_id)
        # Map question type to Chinese
        if self.question_type:
            self.question_type_zh = QUESTION_TYPE_MAP.get(self.question_type, self.question_type)
        return self


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
