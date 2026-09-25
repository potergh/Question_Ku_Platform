"""Selection basket models — temporary question basket for practice building."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SelectionBasket(Base):
    """V1 只有一个全局选题池（无账号），按需懒创建。"""

    __tablename__ = "selection_baskets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())


class SelectionBasketItem(Base):
    """选题池条目：只引用题库题目，不复制内容。"""

    __tablename__ = "selection_basket_items"
    __table_args__ = (UniqueConstraint("basket_id", "question_id", name="uq_basket_question"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    basket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
