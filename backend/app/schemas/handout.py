"""Pydantic schemas for Handout."""

from datetime import datetime
from pydantic import BaseModel


class HandoutItemResponse(BaseModel):
    id: str
    handout_id: str
    order: int
    item_type: str
    question_id: str | None
    question_snapshot: dict | None
    custom_content: str | None
    show_answer: bool
    config: dict | None

    model_config = {"from_attributes": True}


class HandoutResponse(BaseModel):
    id: str
    title: str
    subject: str | None
    target_student: dict | None
    teaching_notes: str | None
    status: str
    config: dict | None
    items: list[HandoutItemResponse] = []
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class HandoutCreate(BaseModel):
    title: str
    subject: str | None = None
    target_student: dict | None = None
    teaching_notes: str | None = None


class HandoutUpdate(BaseModel):
    title: str | None = None
    subject: str | None = None
    target_student: dict | None = None
    teaching_notes: str | None = None
    status: str | None = None
    config: dict | None = None


class AddItemRequest(BaseModel):
    item_type: str = "question"  # question / section_title / knowledge_note / example / exercise
    question_id: str | None = None
    custom_content: str | None = None
    show_answer: bool = True


class UpdateItemRequest(BaseModel):
    custom_content: str | None = None
    show_answer: bool | None = None
    config: dict | None = None


class ReorderRequest(BaseModel):
    item_ids: list[str]  # ordered list of item IDs


class HandoutListResponse(BaseModel):
    handouts: list[HandoutResponse]
    total: int
