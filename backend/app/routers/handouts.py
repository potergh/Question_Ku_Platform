"""Handout router — CRUD, item management, reorder, export."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Handout, HandoutItem, Question
from app.schemas.handout import (
    HandoutResponse, HandoutCreate, HandoutUpdate,
    HandoutListResponse, HandoutItemResponse,
    AddItemRequest, UpdateItemRequest, ReorderRequest,
)

router = APIRouter()


@router.get("/api/handouts", response_model=HandoutListResponse)
async def list_handouts(db: AsyncSession = Depends(get_db)):
    """List all handouts with their items."""
    result = await db.execute(
        select(Handout).options(selectinload(Handout.items)).order_by(Handout.created_at.desc())
    )
    handouts = result.scalars().all()
    return HandoutListResponse(handouts=handouts, total=len(handouts))


@router.post("/api/handouts", response_model=HandoutResponse)
async def create_handout(data: HandoutCreate, db: AsyncSession = Depends(get_db)):
    """Create a new handout."""
    handout = Handout(
        title=data.title,
        subject=data.subject,
        target_student=data.target_student,
        teaching_notes=data.teaching_notes,
    )
    db.add(handout)
    await db.commit()
    await db.refresh(handout, ["items"])
    return handout


@router.get("/api/handouts/{handout_id}", response_model=HandoutResponse)
async def get_handout(handout_id: str, db: AsyncSession = Depends(get_db)):
    """Get a handout with all its items."""
    result = await db.execute(
        select(Handout).where(Handout.id == handout_id).options(selectinload(Handout.items))
    )
    handout = result.scalar_one_or_none()
    if not handout:
        raise HTTPException(404, "Handout not found")
    return handout


@router.put("/api/handouts/{handout_id}", response_model=HandoutResponse)
async def update_handout(
    handout_id: str, data: HandoutUpdate, db: AsyncSession = Depends(get_db)
):
    """Update handout metadata."""
    result = await db.execute(
        select(Handout).where(Handout.id == handout_id).options(selectinload(Handout.items))
    )
    handout = result.scalar_one_or_none()
    if not handout:
        raise HTTPException(404, "Handout not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(handout, field, value)

    await db.commit()
    await db.refresh(handout, ["items"])
    return handout


@router.delete("/api/handouts/{handout_id}")
async def delete_handout(handout_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a handout and all its items."""
    handout = await db.get(Handout, handout_id)
    if not handout:
        raise HTTPException(404, "Handout not found")
    await db.delete(handout)
    await db.commit()
    return {"ok": True}


@router.post("/api/handouts/{handout_id}/items", response_model=HandoutItemResponse)
async def add_item(
    handout_id: str, data: AddItemRequest, db: AsyncSession = Depends(get_db)
):
    """Add a question or custom item to the handout."""
    handout = await db.get(Handout, handout_id)
    if not handout:
        raise HTTPException(404, "Handout not found")

    # Determine next order
    result = await db.execute(
        select(func.max(HandoutItem.order)).where(HandoutItem.handout_id == handout_id)
    )
    max_order = result.scalar() or 0
    next_order = max_order + 1

    # Build snapshot if adding a question-based item
    snapshot = None
    if data.item_type in ("question", "example", "exercise") and data.question_id:
        question = await db.get(Question, data.question_id)
        if not question or question.is_deleted:
            raise HTTPException(404, "Question not found")
        snapshot = {
            "content": question.content,
            "options": question.options,
            "answer": question.answer,
            "explanation": question.explanation,
            "question_type": question.question_type,
            "score": question.score,
            "question_number": question.question_number,
        }

    item = HandoutItem(
        handout_id=handout_id,
        order=next_order,
        item_type=data.item_type,
        question_id=data.question_id,
        question_snapshot=snapshot,
        custom_content=data.custom_content,
        show_answer=data.show_answer,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/api/handouts/{handout_id}/items/{item_id}", response_model=HandoutItemResponse)
async def update_item(
    handout_id: str, item_id: str, data: UpdateItemRequest, db: AsyncSession = Depends(get_db)
):
    """Update an item's content or config."""
    item = await db.get(HandoutItem, item_id)
    if not item or item.handout_id != handout_id:
        raise HTTPException(404, "Item not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/api/handouts/{handout_id}/items/{item_id}")
async def remove_item(
    handout_id: str, item_id: str, db: AsyncSession = Depends(get_db)
):
    """Remove an item from the handout."""
    item = await db.get(HandoutItem, item_id)
    if not item or item.handout_id != handout_id:
        raise HTTPException(404, "Item not found")
    await db.delete(item)
    await db.commit()
    return {"ok": True}


@router.post("/api/handouts/{handout_id}/reorder")
async def reorder_items(
    handout_id: str, data: ReorderRequest, db: AsyncSession = Depends(get_db)
):
    """Reorder items in the handout."""
    result = await db.execute(
        select(HandoutItem).where(HandoutItem.handout_id == handout_id)
    )
    items = {item.id: item for item in result.scalars().all()}

    for new_order, item_id in enumerate(data.item_ids, start=1):
        if item_id in items:
            items[item_id].order = new_order

    await db.commit()
    return {"ok": True}


@router.post("/api/handouts/{handout_id}/items/{item_id}/toggle-answer")
async def toggle_answer(
    handout_id: str, item_id: str, db: AsyncSession = Depends(get_db)
):
    """Toggle whether answer is shown for an item."""
    item = await db.get(HandoutItem, item_id)
    if not item or item.handout_id != handout_id:
        raise HTTPException(404, "Item not found")
    item.show_answer = not item.show_answer
    await db.commit()
    return {"ok": True, "show_answer": item.show_answer}


@router.post("/api/handouts/{handout_id}/export")
async def export_handout_pdf(
    handout_id: str, db: AsyncSession = Depends(get_db)
):
    """Export handout as PDF using Playwright + KaTeX."""
    result = await db.execute(
        select(Handout).where(Handout.id == handout_id).options(selectinload(Handout.items))
    )
    handout = result.scalar_one_or_none()
    if not handout:
        raise HTTPException(404, "Handout not found")
    if not handout.items:
        raise HTTPException(400, "Handout has no items")

    # Generate HTML
    html = _render_handout_html(handout)

    # Use Playwright to render and export PDF
    import asyncio
    from playwright.async_api import async_playwright

    output_path = settings.export_dir / f"{handout_id}.pdf"
    settings.export_dir.mkdir(parents=True, exist_ok=True)

    async def _export():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
            )
            await browser.close()

    await _export()

    # Update handout status
    handout.status = "exported"
    await db.commit()

    return FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=f"{handout.title}.pdf",
    )


def _render_handout_html(handout: Handout) -> str:
    """Render handout as HTML with KaTeX support."""
    items_html = []
    for item in sorted(handout.items, key=lambda i: i.order):
        if item.item_type == "section_title":
            items_html.append(f'<h2 class="section-title">{item.custom_content or ""}</h2>')
        elif item.item_type in ("question", "example", "exercise") and item.question_snapshot:
            snap = item.question_snapshot
            content = snap.get("content", "") or ""
            # Escape HTML but preserve Markdown structure
            content = _markdown_to_html(content)

            options_html = ""
            options = snap.get("options") or []
            if options:
                opt_items = [f"<li><b>{o.get('label', chr(65+i))}.</b> {o.get('content', '')}</li>" for i, o in enumerate(options)]
                options_html = f'<ul class="options">{"".join(opt_items)}</ul>'

            answer_html = ""
            if item.show_answer:
                answer = snap.get("answer") or ""
                explanation = snap.get("explanation") or ""
                if answer or explanation:
                    answer_html = f'''<div class="answer-section">
                        <div class="answer"><b>答案：</b>{_markdown_to_html(answer)}</div>
                        {"<div class='explanation'><b>解析：</b>" + _markdown_to_html(explanation) + "</div>" if explanation else ""}
                    </div>'''

            score = snap.get("score")
            score_html = f'<span class="score">({score}分)</span>' if score else ""
            q_num = snap.get("question_number", "")

            items_html.append(f'''<div class="question-card">
                <div class="q-header">
                    <span class="q-number">第 {q_num} 题</span> {score_html}
                </div>
                <div class="q-content">{content}</div>
                {options_html}
                {answer_html}
            </div>''')
        elif item.item_type == "knowledge_note":
            items_html.append(f'<div class="knowledge-note">{_markdown_to_html(item.custom_content or "")}</div>')

    body = "\n".join(items_html)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
    onload="renderMathInElement(document.body, {{delimiters: [
        {{left: '$$', right: '$$', display: true}},
        {{left: '$', right: '$', display: false}}
    ]}});"></script>
<style>
    body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; font-size: 14px; line-height: 1.8; color: #333; }}
    h1 {{ text-align: center; font-size: 22px; margin-bottom: 8px; }}
    .subtitle {{ text-align: center; color: #666; margin-bottom: 30px; font-size: 13px; }}
    .section-title {{ font-size: 17px; margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #409eff; color: #303133; }}
    .question-card {{ margin-bottom: 20px; padding: 12px 16px; border: 1px solid #e4e7ed; border-radius: 6px; page-break-inside: avoid; }}
    .q-header {{ margin-bottom: 8px; }}
    .q-number {{ font-weight: bold; font-size: 15px; }}
    .score {{ color: #909399; font-size: 13px; margin-left: 8px; }}
    .q-content {{ margin-bottom: 8px; }}
    .options {{ list-style: none; padding-left: 8px; }}
    .options li {{ margin-bottom: 4px; }}
    .answer-section {{ margin-top: 10px; padding: 8px 12px; background: #f0f9eb; border-radius: 4px; font-size: 13px; }}
    .answer {{ color: #67c23a; }}
    .explanation {{ margin-top: 4px; color: #606266; }}
    .knowledge-note {{ margin: 16px 0; padding: 12px; background: #ecf5ff; border-radius: 6px; border-left: 3px solid #409eff; }}
</style>
</head>
<body>
<h1>{handout.title}</h1>
<div class="subtitle">{handout.subject or ""}</div>
{body}
</body>
</html>"""


def _markdown_to_html(text: str) -> str:
    """Minimal Markdown to HTML conversion for handout rendering."""
    import re
    if not text:
        return ""

    # Preserve LaTeX ($...$) by not touching it
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Line breaks
    text = text.replace('\n', '<br>')
    return text
