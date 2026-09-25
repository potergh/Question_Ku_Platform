"""Pydantic schemas for Tag."""

from datetime import datetime
from pydantic import BaseModel


class TagResponse(BaseModel):
    id: str
    name: str
    subject: str | None = None
    category: str
    color: str | None
    parent_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    name: str
    subject: str | None = None
    category: str
    color: str | None = None
    parent_id: str | None = None


class TagUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    color: str | None = None
    parent_id: str | None = None


class TagTree(BaseModel):
    """Tag with children for tree display."""
    id: str
    name: str
    subject: str | None = None
    category: str
    color: str | None
    parent_id: str | None
    children: list["TagTree"] = []
