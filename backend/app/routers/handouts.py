"""Handout router — CRUD, item management, reorder, export."""

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
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


async def _patch_snapshots(handouts_or_handout, db: AsyncSession):
    """Ensure question_snapshot has source_id for all items (patch old data)."""
    # Normalize to list of items
    if isinstance(handouts_or_handout, list):
        all_items = []
        for h in handouts_or_handout:
            all_items.extend(h.items)
    else:
        all_items = handouts_or_handout.items

    # Find items missing source_id in snapshot
    need_patch = []
    for item in all_items:
        if (item.question_snapshot is not None
                and not item.question_snapshot.get("source_id")
                and item.question_id):
            need_patch.append(item)

    if need_patch:
        for item in need_patch:
            q = await db.get(Question, item.question_id)
            if q:
                item.question_snapshot["source_id"] = q.source_id
        await db.commit()


@router.get("/api/handouts", response_model=HandoutListResponse)
async def list_handouts(db: AsyncSession = Depends(get_db)):
    """List all handouts with their items."""
    result = await db.execute(
        select(Handout).options(selectinload(Handout.items)).order_by(Handout.created_at.desc())
    )
    handouts = result.scalars().all()
    await _patch_snapshots(handouts, db)
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
    await _patch_snapshots(handout, db)
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
            "source_id": question.source_id,
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
async def export_handout(
    handout_id: str,
    format: str = Query(default="pdf", description="pdf | docx"),
    version: str = Query(default="teacher", description="student | teacher"),
    db: AsyncSession = Depends(get_db),
):
    """Export handout as PDF or Word (student/teacher version)."""
    result = await db.execute(
        select(Handout).where(Handout.id == handout_id).options(selectinload(Handout.items))
    )
    handout = result.scalar_one_or_none()
    if not handout:
        raise HTTPException(404, "Handout not found")
    if not handout.items:
        raise HTTPException(400, "Handout has no items")

    settings.export_dir.mkdir(parents=True, exist_ok=True)

    if format == "docx":
        # Word export
        from app.services.word_export import generate_word
        from app.models import Source

        # Build source OCR dirs mapping
        source_ocr_dirs = {}
        for item in handout.items:
            sid = None
            if item.question_snapshot and item.question_snapshot.get("source_id"):
                sid = item.question_snapshot["source_id"]
            elif item.question_id:
                q = await db.get(Question, item.question_id)
                if q:
                    sid = q.source_id
            if sid and sid not in source_ocr_dirs:
                source = await db.get(Source, sid)
                if source and source.ocr_result_path:
                    source_ocr_dirs[sid] = source.ocr_result_path
        
        buffer = generate_word(handout, version=version, source_ocr_dirs=source_ocr_dirs)
        version_suffix = "_student" if version == "student" else "_teacher"
        filename = f"{handout.title}{version_suffix}.docx"
        output_path = settings.export_dir / f"{handout_id}{version_suffix}.docx"
        
        # Save to file
        with open(output_path, "wb") as f:
            f.write(buffer.read())
        
        # Update handout status
        handout.status = "exported"
        await db.commit()
        
        return FileResponse(
            str(output_path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=filename,
        )
    else:
        # PDF export (default)
        html = await _render_handout_html(handout, db)

        # Use Playwright to render and export PDF
        import asyncio
        import tempfile
        from pathlib import Path as _Path
        from playwright.async_api import async_playwright

        output_path = settings.export_dir / f"{handout_id}.pdf"

        async def _export():
            async with async_playwright() as p:
                browser = await p.chromium.launch(args=["--allow-file-access-from-files"])
                page = await browser.new_page()
                # Write HTML to temp file so file:// image URLs resolve correctly
                # (set_content uses about:blank as base, blocking file:// images)
                tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
                tmp.write(html)
                tmp.close()
                try:
                    file_url = _Path(tmp.name).as_uri()
                    await page.goto(file_url, wait_until="networkidle", timeout=30000)
                    await page.pdf(
                        path=str(output_path),
                        format="A4",
                        print_background=True,
                        margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"},
                    )
                finally:
                    _Path(tmp.name).unlink(missing_ok=True)
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


async def _render_handout_html(handout: Handout, db: AsyncSession) -> str:
    """Render handout as HTML with KaTeX support and resolved images."""
    # Pre-load source OCR paths for image resolution
    source_ocr_dirs = {}
    source_ids = set()
    for item in handout.items:
        sid = None
        if item.question_snapshot and item.question_snapshot.get("source_id"):
            sid = item.question_snapshot["source_id"]
        elif item.question_id:
            # Fallback: look up source_id from the question
            q = await db.get(Question, item.question_id)
            if q:
                sid = q.source_id
                # Also patch the snapshot for future use
                if item.question_snapshot is not None:
                    item.question_snapshot["source_id"] = sid
        if sid:
            source_ids.add(sid)
    if source_ids:
        from app.models import Source
        for sid in source_ids:
            source = await db.get(Source, sid)
            if source and source.ocr_result_path:
                source_ocr_dirs[sid] = source.ocr_result_path

    items_html = []
    for item in sorted(handout.items, key=lambda i: i.order):
        if item.item_type == "section_title":
            items_html.append(f'<h2 class="section-title">{item.custom_content or ""}</h2>')
        elif item.item_type in ("question", "example", "exercise") and item.question_snapshot:
            snap = item.question_snapshot
            content = snap.get("content", "") or ""
            source_id = snap.get("source_id", "")
            ocr_dir = source_ocr_dirs.get(source_id, "")
            # Resolve asset:// URLs and convert to HTML
            content = _markdown_to_html(content, ocr_dir=ocr_dir)

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
    .q-content img {{ max-width: 100%; height: auto; margin: 8px 0; display: block; }}
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


def _markdown_to_html(text: str, ocr_dir: str = "") -> str:
    """Minimal Markdown to HTML conversion for handout rendering.
    
    Handles images, LaTeX, bold, italic, and line breaks.
    If ocr_dir is provided, asset:// URLs are resolved to local file:// paths.
    """
    import re
    if not text:
        return ""

    # Images: ![alt](url) → <img>
    def _img_replace(m):
        alt = m.group(1)
        url = m.group(2)
        # Resolve asset:// URLs to file:// paths
        if url.startswith("asset://") and ocr_dir:
            path = url[len("asset://"):]
            # Normalize double figures/figures/ → figures/
            path = re.sub(r'^figures/figures/', 'figures/', path)
            from pathlib import Path
            file_path = Path(ocr_dir) / path
            if file_path.exists():
                url = file_path.as_uri()
        elif url.startswith("/api/ocr-assets/"):
            # Convert API URL back to file path
            parts = url.split("/", 4)  # ['', 'api', 'ocr-assets', 'source_id', 'path']
            if len(parts) >= 5 and ocr_dir:
                from pathlib import Path
                file_path = Path(ocr_dir) / parts[4]
                # Normalize double figures/
                normalized = re.sub(r'^figures/figures/', 'figures/', parts[4])
                file_path = Path(ocr_dir) / normalized
                if file_path.exists():
                    url = file_path.as_uri()
        return f'<img src="{url}" alt="{alt}" style="max-width:100%;height:auto;margin:6px 0;" />'

    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _img_replace, text)

    # Preserve LaTeX ($...$) by not touching it — KaTeX auto-render handles it
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Line breaks
    text = text.replace('\n', '<br>')
    return text


# ── AI Generate ─────────────────────────────────────────────────────


@router.post("/api/handouts/{handout_id}/ai-generate")
async def ai_generate(
    handout_id: str,
    action: str = Query(..., description="recommend_questions | suggest_structure | generate_notes"),
    student_profile: str = Body("", embed=True),
    topic: str = Body("", embed=True),
    context: str = Body("", embed=True),
    count: int = Body(5, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """AI-powered handout assistance: recommend questions, suggest structure, generate notes."""
    from app.services.ai_service import (
        recommend_questions, suggest_structure, generate_notes, AIServiceError,
    )
    from app.models import Tag

    result = await db.execute(
        select(Handout).where(Handout.id == handout_id).options(selectinload(Handout.items))
    )
    handout = result.scalar_one_or_none()
    if not handout:
        raise HTTPException(404, "Handout not found")

    try:
        if action == "recommend_questions":
            existing_ids = [
                item.question_id for item in handout.items
                if item.question_id and item.item_type in ("question", "example", "exercise")
            ]
            results = await recommend_questions(
                db, handout_id, student_profile, existing_ids, count
            )
            # Enrich with question content
            enriched = []
            for rec in results:
                q = await db.get(Question, rec["question_id"])
                if q:
                    enriched.append({
                        **rec,
                        "content": (q.content or "")[:150],
                        "question_type": q.question_type,
                    })
            return {"ok": True, "data": enriched}

        elif action == "suggest_structure":
            # Get all tags for reference
            tag_result = await db.execute(select(Tag).order_by(Tag.category, Tag.name))
            tags = [{"id": t.id, "name": t.name, "category": t.category} for t in tag_result.scalars().all()]
            results = await suggest_structure(db, handout.subject or "物理", student_profile, tags)
            return {"ok": True, "data": results}

        elif action == "generate_notes":
            result = await generate_notes(db, topic, student_profile, context)
            return {"ok": True, "data": {"markdown": result}}

        else:
            raise HTTPException(400, f"Unknown action: {action}")

    except AIServiceError as e:
        raise HTTPException(400, str(e))
