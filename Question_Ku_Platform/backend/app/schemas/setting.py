"""Pydantic schemas for Settings."""

from pydantic import BaseModel


class SettingsResponse(BaseModel):
    ai_mode: str  # 识别模式：off / remote / mineru（+ 历史值 local）
    ai_api_key_masked: str | None = None
    ai_base_url: str
    ai_model: str
    # 视觉模型（api_extract 通道用），与文本模型独立配置。
    ai_vision_model: str = "qwen-vl-max"
    # 视觉模型端点；留空时后端回退到 ai_base_url。
    ai_vision_base_url: str | None = None
    # 视觉模型独立 Key，按 ai_api_key 同一套规则打码返回。
    ai_vision_api_key_masked: str | None = None
    ai_temperature: float
    ai_review_prompt: str | None = None
    # MinerU 识别通道的 Token，按 ai_api_key 同一套规则打码返回。
    mineru_api_token_masked: str | None = None
    # MinerU 解析参数（非密钥，明文回显）。
    mineru_model_version: str = "vlm"
    mineru_language: str = "ch"
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True


class SettingsUpdate(BaseModel):
    ai_mode: str | None = None
    ai_api_key: str | None = None  # send full key to update, omit to keep existing
    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_vision_model: str | None = None
    ai_vision_base_url: str | None = None
    ai_vision_api_key: str | None = None  # 同 ai_api_key：留空表示保留原值
    ai_temperature: float | None = None
    ai_review_prompt: str | None = None
    mineru_api_token: str | None = None  # 同 ai_api_key：留空表示保留原值
    mineru_model_version: str | None = None
    mineru_language: str | None = None
    mineru_enable_formula: bool | None = None
    mineru_enable_table: bool | None = None


class TestConnectionRequest(BaseModel):
    base_url: str
    api_key: str
    model: str
    # 测的是文本模型还是视觉模型：决定"留空回退已保存 Key"时回退到哪一个 ——
    # 两个模型可以各持独立 Key（视觉 Key 留空还会再回退文本 Key）。
    kind: str = "text"


class TestConnectionResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
