"""Question router — list, update, review, soft-delete questions."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Question, Source
from app.schemas.question import QuestionResponse, QuestionUpdate, QuestionListResponse

router = APIRouter()


@router.get("/api/questions", response_model=QuestionListResponse)
async def list_questions(
    source_id: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    question_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List questions with optional filters."""
    query = select(Question).where(Question.is_deleted == False)

    if source_id:
        query = query.where(Question.source_id == source_id)
    if review_status:
        query = query.where(Question.review_status == review_status)
    if question_type:
        query = query.where(Question.question_type == question_type)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.order_by(Question.question_number).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    questions = result.scalars().all()

    return QuestionListResponse(questions=questions, total=total)


@router.get("/api/questions/{question_id}", response_model=QuestionResponse)
async def get_question(question_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single question by ID."""
    question = await db.get(Question, question_id)
    if not question or question.is_deleted:
        raise HTTPException(404, "Question not found")
    return question


@router.put("/api/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: str,
    update: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update question content (user edits)."""
    question = await db.get(Question, question_id)
    if not question or question.is_deleted:
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
