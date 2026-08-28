"""Practice router — create from basket, list, detail, update, delete, assets."""

import shutil

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Question
from app.models.basket import SelectionBasketItem
from app.models.practice import Practice, PracticeQuestion, PracticeSection
from app.schemas.practice import (
    PracticeBrief, PracticeCreateRequest, PracticeListResponse,
    PracticeQuestionOut, PracticeResponse, PracticeSectionOut, PracticeUpdateRequest,
)
from app.services import practice_service

router = APIRouter()


async def _load_questions_ordered(db: AsyncSession, qids: list[str]) -> list[Question]:
    if not qids:
        return []
    result = await db.execute(
        select(Question).where(Question.id.in_(qids), Question.is_deleted == False)
    )
    qmap = {q.id: q for q in result.scalars().all()}
    return [qmap[qid] for qid in qids if qid in qmap]


async def _get_practice_full(db: AsyncSession, practice_id: str) -> Practice | None:
    result = await db.execute(
        select(Practice).where(Practice.id == practice_id)
        .options(selectinload(Practice.sections).selectinload(PracticeSection.questions))
    )
    return result.scalar_one_or_none()


def _practice_response(practice: Practice) -> PracticeResponse:
    sections, total = [], 0
    for s in practice.sections:
        questions = [
            PracticeQuestionOut(
                id=pq.id, position=pq.position, source_question_id=pq.source_question_id,
                question_number=pq.question_number, question_type=pq.question_type,
                difficulty=pq.difficulty, score=pq.score,
                content=practice_service.resolve_practice_asset_urls(pq.content_snapshot, practice.id),
                options=pq.options_snapshot, is_modified=pq.is_modified,
            )
            for pq in s.questions
        ]
        total += len(questions)
        sections.append(PracticeSectionOut(
            id=s.id, title=s.title, section_type=s.section_type, position=s.position,
            show_title=s.show_title, start_on_new_page=s.start_on_new_page, questions=questions,
        ))
    return PracticeResponse(
        id=practice.id, title=practice.title, subtitle=practice.subtitle,
        subject=practice.subject, grade=practice.grade, status=practice.status,
        question_count=total, created_at=practice.created_at, updated_at=practice.updated_at,
        sections=sections,
    )


@router.post("/api/practices", response_model=PracticeResponse)
async def create_practice(req: PracticeCreateRequest, db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    if req.from_basket:
        result = await db.execute(
            select(SelectionBasketItem)
            .where(SelectionBasketItem.basket_id == basket.id)
            .order_by(SelectionBasketItem.position)
        )
        qids = [it.question_id for it in result.scalars().all()]
    else:
        qids = req.question_ids or []

    questions = await _load_questions_ordered(db, qids)
    if not questions:
        raise HTTPException(400, "没有可用题目：选题池为空或题目已删除")

    practice = await practice_service.create_practice_from_questions(
        db, req.title, req.subtitle, req.subject, req.grade, questions,
    )

    if req.from_basket and req.clear_basket:
        await db.execute(delete(SelectionBasketItem).where(SelectionBasketItem.basket_id == basket.id))
        await db.commit()

    practice = await _get_practice_full(db, practice.id)
    return _practice_response(practice)


@router.get("/api/practices", response_model=PracticeListResponse)
async def list_practices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Practice).order_by(Practice.created_at.desc()))
    briefs = []
    for p in result.scalars().all():
        cnt = await db.execute(
            select(func.count()).select_from(PracticeQuestion)
            .where(PracticeQuestion.practice_id == p.id)
        )
        briefs.append(PracticeBrief(
            id=p.id, title=p.title, subtitle=p.subtitle, subject=p.subject, grade=p.grade,
            status=p.status, question_count=cnt.scalar() or 0,
            created_at=p.created_at, updated_at=p.updated_at,
        ))
    return PracticeListResponse(practices=briefs, total=len(briefs))


@router.get("/api/practices/{practice_id}", response_model=PracticeResponse)
async def get_practice(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    return _practice_response(practice)


@router.put("/api/practices/{practice_id}", response_model=PracticeResponse)
async def update_practice(practice_id: str, req: PracticeUpdateRequest, db: AsyncSession = Depends(get_db)):
    practice = await db.get(Practice, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(practice, field, value)
    await db.commit()
    return await get_practice(practice_id, db)


@router.delete("/api/practices/{practice_id}")
async def delete_practice(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await db.get(Practice, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    await db.delete(practice)
    await db.commit()
    shutil.rmtree(practice_service.practices_root() / practice_id, ignore_errors=True)
    return {"ok": True}


@router.get("/api/practices/{practice_id}/assets/{path:path}")
async def serve_practice_asset(practice_id: str, path: str):
    assets_dir = practice_service.practice_assets_dir(practice_id)
    file_path = (assets_dir / path)
    try:
        file_path.resolve().relative_to(assets_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, f"Asset not found: {path}")
    return FileResponse(str(file_path))
