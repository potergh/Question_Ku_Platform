"""Pydantic schemas for Question."""

from datetime import datetime
from pydantic import BaseModel, model_validator, Field

from app.utils.assets import resolve_asset_urls, resolve_card_image_path
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
    # 语篇题（完形/阅读等）的两级结构：{label,stem,options,answer,explanation} 列表。
    # 普通题为 None；前端据此判断是否按「材料+小题」渲染。
    sub_questions: list | None = None
    answer: str | None
    explanation: str | None
    score: float | None
    card_image_path: str | None
    # 答案区插图，出参时已转成 HTTP URL（入库存的是绝对路径）。
    # 卷面答案是图时 answer 只有「如上图所示」，图本身在这里。
    # 可为 None：迁移前的存量行这一列是 NULL，validator 会归一成空列表。
    answer_image_paths: list[str] | None = None
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
            self.answer_image_paths = [
                (resolve_card_image_path(path, self.source_id) or path)
                for path in (self.answer_image_paths or [])
            ]
            # Also resolve asset:// URLs in options
            if self.options and isinstance(self.options, list):
                for opt in self.options:
                    if isinstance(opt, dict) and opt.get('content') and 'asset://' in str(opt['content']):
                        opt['content'] = resolve_asset_urls(opt['content'], self.source_id)
            # 语篇题小题的选项/题干也可能带 asset:// 内联图，统一解析成 HTTP URL。
            if self.sub_questions and isinstance(self.sub_questions, list):
                for sub in self.sub_questions:
                    if not isinstance(sub, dict):
                        continue
                    if sub.get('stem') and 'asset://' in str(sub['stem']):
                        sub['stem'] = resolve_asset_urls(sub['stem'], self.source_id)
                    for opt in (sub.get('options') or []):
                        if isinstance(opt, dict) and opt.get('content') and 'asset://' in str(opt['content']):
                            opt['content'] = resolve_asset_urls(opt['content'], self.source_id)
        # Map question type to Chinese
        if self.question_type:
            self.question_type_zh = QUESTION_TYPE_MAP.get(self.question_type, self.question_type)
        return self


class QuestionUpdate(BaseModel):
    content: str | None = None
    options: list | None = None
    sub_questions: list | None = None
    answer: str | None = None
    explanation: str | None = None
    question_type: str | None = None
    difficulty: int | None = None
    grade: str | None = None
    subject: str | None = None


class QuestionListResponse(BaseModel):
    questions: list[QuestionResponse]
    total: int
