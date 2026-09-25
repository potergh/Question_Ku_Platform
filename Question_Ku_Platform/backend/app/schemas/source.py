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
    # paper = 正常试卷/讲义；answer_doc = 只作为答案来源的配套文档，
    # 不产出题目，默认不出现在常规列表里。
    role: str = "paper"
    # local_ocr / api_extract；历史数据为 None，前端按 local_ocr 处理。
    extract_channel: str | None = None
    # 指向本文档的答案文档 source（仅 role=paper 时可能有值）。
    companion_source_id: str | None = None

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    sources: list[SourceResponse]
    total: int
