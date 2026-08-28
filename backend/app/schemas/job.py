"""Pydantic schemas for Job."""

from datetime import datetime
from pydantic import BaseModel


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    progress: float
    source_id: str | None
    error_message: str | None
    cancelled: bool = False
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Denormalized from source for display
    filename: str | None = None
    ocr_status: str | None = None

    model_config = {"from_attributes": True}
