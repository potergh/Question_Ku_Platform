"""Pydantic schemas for Settings."""

from pydantic import BaseModel


class SettingsResponse(BaseModel):
    ai_mode: str  # off / local / remote
    ai_api_key_masked: str | None = None
    ai_base_url: str
    ai_model: str
    ai_temperature: float
    ai_review_prompt: str | None = None


class SettingsUpdate(BaseModel):
    ai_mode: str | None = None
    ai_api_key: str | None = None  # send full key to update, omit to keep existing
    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_temperature: float | None = None
    ai_review_prompt: str | None = None


class TestConnectionRequest(BaseModel):
    base_url: str
    api_key: str
    model: str


class TestConnectionResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
