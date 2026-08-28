"""Settings model — AI config stored in DB, API key masked on read."""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Settings(Base):
    """Singleton settings row. AI mode: off / local / remote."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    ai_mode: Mapped[str] = mapped_column(String(20), default="off")  # off/local/remote
    ai_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ai_base_url: Mapped[str] = mapped_column(String(500), default="https://api.openai.com/v1")
    ai_model: Mapped[str] = mapped_column(String(100), default="gpt-4o")
    ai_temperature: Mapped[float] = mapped_column(Float, default=0.7)
    ai_review_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    @staticmethod
    def mask_key(key: str | None) -> str | None:
        """Mask API key for safe display: sk-****xyz"""
        if not key or len(key) < 8:
            return None
        return f"{key[:4]}****{key[-4:]}"
