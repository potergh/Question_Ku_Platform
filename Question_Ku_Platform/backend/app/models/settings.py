"""Settings model — AI config stored in DB, API key masked on read."""

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Settings(Base):
    """Singleton settings row. AI mode: off / local / remote."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # 识别模式。取值：off（本地识别，纯本机 OCR 不调用 AI）/ remote（大模型识别）/
    # mineru（MinerU 混合识别：MinerU 解析排版 + 大模型切题，同样需要 AI 配置）/
    # local（历史值：本地模型）。后端只判断「是否等于 off」与「是否等于 local」，
    # 所以 mineru 自动沿用远程 API 那套配置 —— 这正是混合识别需要的。
    ai_mode: Mapped[str] = mapped_column(String(20), default="off")
    ai_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Base URL 与模型名默认**留空**：写死的预设值会让人误以为"已经能用了"，
    # 实际一保存就拿我们替用户选的厂商去请求，报错信息还夹着厂商的 401。
    # 留空则第一次配置就能明确知道"这两格是我必须填的"（前端有预设下拉可一键带出）。
    ai_base_url: Mapped[str] = mapped_column(String(500), default="")
    ai_model: Mapped[str] = mapped_column(String(100), default="")
    # 视觉模型，用于 api_extract 通道识别题卡图/扫描页；与文本模型分开配置。
    ai_vision_model: Mapped[str] = mapped_column(String(100), default="qwen-vl-max")
    # 视觉模型端点；留空时回退到 ai_base_url。文本模型与视觉模型常常不同供应商
    # （如 gpt-4o 走 OpenAI、qwen-vl-max 走 DashScope compatible-mode），必须能分开配。
    ai_vision_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 视觉模型独立 Key；留空回退到 ai_api_key。与 base_url 同理：视觉模型常属
    # 另一家供应商，Key 各自独立，混用一个 Key 只会在调用时报 401、排查半天。
    ai_vision_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ai_temperature: Mapped[float] = mapped_column(Float, default=0.7)
    ai_review_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # MinerU 识别通道的 Token（mineru.net 申请，Bearer 鉴权）。与 ai_api_key 无关：
    # 它是独立供应商的凭证，不用这个通道时留空。
    mineru_api_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # MinerU 解析参数。默认值即官方默认值：迁移后行为与迁移前一致。
    # model_version：vlm 把选择题选项拆成独立块，pipeline 会挤成一行，
    # 对下游逐题结构化差别明显，所以默认 vlm（见 mineru_client 的实测记录）。
    mineru_model_version: Mapped[str] = mapped_column(
        String(20), default="vlm", nullable=False
    )
    mineru_language: Mapped[str] = mapped_column(String(20), default="ch", nullable=False)
    mineru_enable_formula: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    mineru_enable_table: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    @staticmethod
    def mask_key(key: str | None) -> str | None:
        """Mask API key for safe display: sk-****xyz"""
        if not key or len(key) < 8:
            return None
        return f"{key[:4]}****{key[-4:]}"
