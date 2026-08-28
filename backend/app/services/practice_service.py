"""Practice service — basket helpers, snapshot creation, asset copying."""

import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.basket import SelectionBasket

ASSET_RE = re.compile(r"asset://([^\s\)]+)")

# 小节按题型生成时的固定顺序
SECTION_TYPE_ORDER = [
    "选择题", "多选题", "填空题", "实验题", "计算题",
    "解答题", "简答题", "论述题", "综合题", "未知题型",
]


def practices_root() -> Path:
    root = settings.data_dir / "practices"
    root.mkdir(parents=True, exist_ok=True)
    return root


def practice_assets_dir(practice_id: str) -> Path:
    d = practices_root() / practice_id / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def get_or_create_basket(db: AsyncSession) -> SelectionBasket:
    """V1 全局唯一选题池，懒创建。"""
    result = await db.execute(select(SelectionBasket).order_by(SelectionBasket.created_at).limit(1))
    basket = result.scalar_one_or_none()
    if not basket:
        basket = SelectionBasket()
        db.add(basket)
        await db.commit()
        await db.refresh(basket)
    return basket


def resolve_practice_asset_urls(content: str | None, practice_id: str) -> str | None:
    """asset://practice/xxx → /api/practices/{id}/assets/xxx"""
    if not content:
        return content
    return re.sub(
        r"asset://practice/([^\s\)]+)",
        rf"/api/practices/{practice_id}/assets/\1",
        content,
    )
