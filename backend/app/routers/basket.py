"""Selection basket router — global single basket, add/remove/reorder/clear."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Question
from app.models.basket import SelectionBasketItem
from app.schemas.question import QuestionResponse
from app.services import practice_service
from app.utils.question_types import map_question_type

router = APIRouter()


class QuestionIdsRequest(BaseModel):
    question_ids: list[str]


async def _basket_total(db: AsyncSession, basket_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(SelectionBasketItem)
        .where(SelectionBasketItem.basket_id == basket_id)
    )
    return result.scalar() or 0


@router.get("/api/basket")
async def get_basket(db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        select(SelectionBasketItem)
        .where(SelectionBasketItem.basket_id == basket.id)
        .order_by(SelectionBasketItem.position)
    )
    items = result.scalars().all()

    qids = [it.question_id for it in items]
    questions_map = {}
    if qids:
        qr = await db.execute(
            select(Question).where(Question.id.in_(qids)).options(selectinload(Question.tags))
        )
        questions_map = {q.id: q for q in qr.scalars().all()}

    payload_items, type_stats = [], {}
    for it in items:
        q = questions_map.get(it.question_id)
        if not q or q.is_deleted:
            continue
        payload_items.append({
            "id": it.id,
            "position": it.position,
            "question": QuestionResponse.model_validate(q),
        })
        zh = map_question_type(q.question_type)
        type_stats[zh] = type_stats.get(zh, 0) + 1

    return {"basket_id": basket.id, "items": payload_items, "total": len(payload_items), "type_stats": type_stats}


@router.post("/api/basket/items")
async def add_items(req: QuestionIdsRequest, db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        select(SelectionBasketItem).where(SelectionBasketItem.basket_id == basket.id)
    )
    existing = {it.question_id for it in result.scalars().all()}
    result = await db.execute(
        select(func.max(SelectionBasketItem.position)).where(SelectionBasketItem.basket_id == basket.id)
    )
    pos = (result.scalar() or -1) + 1

    added = 0
    for qid in req.question_ids:
        if qid in existing:
            continue
        q = await db.get(Question, qid)
        if not q or q.is_deleted:
            continue
        db.add(SelectionBasketItem(basket_id=basket.id, question_id=qid, position=pos))
        existing.add(qid)
        pos += 1
        added += 1
    await db.commit()
    return {"ok": True, "added": added, "total": await _basket_total(db, basket.id)}


@router.post("/api/basket/items/remove")
async def remove_items(req: QuestionIdsRequest, db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        delete(SelectionBasketItem).where(
            SelectionBasketItem.basket_id == basket.id,
            SelectionBasketItem.question_id.in_(req.question_ids),
        )
    )
    await db.commit()
    return {"ok": True, "removed": result.rowcount, "total": await _basket_total(db, basket.id)}


@router.put("/api/basket/reorder")
async def reorder_items(req: QuestionIdsRequest, db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        select(SelectionBasketItem).where(SelectionBasketItem.basket_id == basket.id)
    )
    items = {it.question_id: it for it in result.scalars().all()}
    for pos, qid in enumerate(req.question_ids):
        if qid in items:
            items[qid].position = pos
    await db.commit()
    return {"ok": True}


@router.delete("/api/basket")
async def clear_basket(db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        delete(SelectionBasketItem).where(SelectionBasketItem.basket_id == basket.id)
    )
    await db.commit()
    return {"ok": True, "removed": result.rowcount}
