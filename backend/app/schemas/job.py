"""Pydantic schemas for Job."""

from datetime import datetime
from pydantic import BaseModel


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    progress: float
    source_id: str | None
    handout_id: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}
