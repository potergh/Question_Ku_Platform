"""Question router — list, update, review, soft-delete, search, batch ops."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Question, Source, Tag, question_tags
from app.schemas.question import QuestionResponse, QuestionUpdate, QuestionListResponse

router = APIRouter()


@router.get("/api/questions", response_model=QuestionListResponse)
async def list_questions(
    source_id: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    question_type: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    difficulty: int | None = Query(default=None),
    grade: str | None = Query(default=None),
    search: str | None = Query(default=None),
    tag_ids: str | None = Query(default=None, description="Comma-separated tag IDs"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List questions with filters and full-text search."""
    query = select(Question).where(Question.is_deleted == False)

    if source_id:
        query = query.where(Question.source_id == source_id)
    if review_status:
        query = query.where(Question.review_status == review_status)
    if question_type:
        query = query.where(Question.question_type == question_type)
    if subject:
        query = query.where(Question.subject == subject)
    if difficulty is not None:
        query = query.where(Question.difficulty == difficulty)
    if grade:
        query = query.where(Question.grade == grade)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Question.content.ilike(pattern),
                Question.answer.ilike(pattern),
                Question.explanation.ilike(pattern),
                Question.raw_ocr_content.ilike(pattern),
            )
        )
    if tag_ids:
        tid_list = [t.strip() for t in tag_ids.split(",") if t.strip()]
        if tid_list:
            query = query.where(
                Question.id.in_(
                    select(question_tags.c.question_id).where(
                        question_tags.c.tag_id.in_(tid_list)
                    )
                )
            )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.options(selectinload(Question.tags)).order_by(Question.question_number).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    questions = result.scalars().all()

    return QuestionListResponse(questions=questions, total=total)


@router.get("/api/questions/{question_id}", response_model=QuestionResponse)
async def get_question(question_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single question by ID."""
    result = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_deleted == False).options(selectinload(Question.tags))
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(404, "Question not found")
    return question


@router.put("/api/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: str,
    update: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update question content (user edits)."""
    result = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_deleted == False).options(selectinload(Question.tags))
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(404, "Question not found")

    # Update only provided fields
    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(question, field, value)

    await db.commit()
    await db.refresh(question)
    return question


@router.post("/api/questions/{question_id}/review")
async def review_question(
    question_id: str,
    action: str = Query(..., description="approve or reject"),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a question after review."""
    question = await db.get(Question, question_id)
    if not question or question.is_deleted:
        raise HTTPException(404, "Question not found")

    if action == "approve":
        question.review_status = "approved"
        question.needs_review = False
    elif action == "reject":
        question.review_status = "rejected"
    else:
        raise HTTPException(400, "action must be 'approve' or 'reject'")

    await db.commit()
    return {"ok": True, "review_status": question.review_status}


@router.delete("/api/questions/{question_id}")
async def delete_question(question_id: str, db: AsyncSession = Depends(get_db)):
    """Soft delete a question."""
    question = await db.get(Question, question_id)
    if not question or question.is_deleted:
        raise HTTPException(404, "Question not found")

    question.is_deleted = True
    question.deleted_at = datetime.now()
    await db.commit()
    return {"ok": True}


@router.post("/api/questions/{question_id}/accept-ai")
async def accept_ai_suggestions(question_id: str, db: AsyncSession = Depends(get_db)):
    """Apply AI suggestions to question fields (tags, difficulty, type)."""
    result = await db.execute(
        select(Question).where(Question.id == question_id, Question.is_deleted == False).options(selectinload(Question.tags))
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(404, "Question not found")
    if not question.ai_suggestions:
        raise HTTPException(400, "No AI suggestions available")

    ai = question.ai_suggestions

    # Apply difficulty if suggested and not already set
    if ai.get("difficulty") and not question.difficulty:
        question.difficulty = ai["difficulty"]

    # Apply question_type if suggested and not already set
    if ai.get("question_type") and not question.question_type:
        question.question_type = ai["question_type"]

    # Apply tags
    if ai.get("tag_ids"):
        for tid in ai["tag_ids"]:
            tag = await db.get(Tag, tid)
            if tag and tag not in question.tags:
                question.tags.append(tag)

    await db.commit()
    await db.refresh(question, ["tags"])
    return {"ok": True, "applied": ai}


# ── Batch operations ────────────────────────────────────────────────


@router.post("/api/questions/batch-tag")
async def batch_tag(
    question_ids: list[str] = Body(..., embed=True),
    tag_ids: list[str] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Add tags to multiple questions."""
    for qid in question_ids:
        question = await db.get(Question, qid)
        if not question or question.is_deleted:
            continue
        for tid in tag_ids:
            tag = await db.get(Tag, tid)
            if tag and tag not in question.tags:
                question.tags.append(tag)
    await db.commit()
    return {"ok": True, "count": len(question_ids)}


@router.post("/api/questions/batch-untag")
async def batch_untag(
    question_ids: list[str] = Body(..., embed=True),
    tag_ids: list[str] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Remove tags from multiple questions."""
    for qid in question_ids:
        question = await db.get(Question, qid)
        if not question or question.is_deleted:
            continue
        question.tags = [t for t in question.tags if t.id not in tag_ids]
    await db.commit()
    return {"ok": True}


@router.post("/api/questions/batch-approve")
async def batch_approve(
    question_ids: list[str] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Approve multiple questions at once."""
    count = 0
    for qid in question_ids:
        question = await db.get(Question, qid)
        if question and not question.is_deleted:
            question.review_status = "approved"
            question.needs_review = False
            count += 1
    await db.commit()
    return {"ok": True, "count": count}


@router.post("/api/questions/batch-delete")
async def batch_delete(
    question_ids: list[str] = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete multiple questions."""
    count = 0
    now = datetime.now()
    for qid in question_ids:
        question = await db.get(Question, qid)
        if question and not question.is_deleted:
            question.is_deleted = True
            question.deleted_at = now
            count += 1
    await db.commit()
    return {"ok": True, "count": count}
