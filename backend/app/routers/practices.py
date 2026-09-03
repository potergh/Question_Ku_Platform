"""Practice router — create from basket, list, detail, update, delete, assets, blocks."""

import asyncio
import io
import json
import re
import shutil

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Question
from app.models.basket import SelectionBasketItem
from app.models.practice import Practice, PracticeContentBlock, PracticeQuestion, PracticeSection
from app.schemas.practice import (
    PracticeBrief, PracticeCreateRequest, PracticeLayoutUpdateRequest, PracticeListResponse,
    PracticeQuestionOut, PracticeResponse, PracticeSectionOut, PracticeUpdateRequest,
    PreviewRenderResponse,
)
from app.services import practice_service, workbook_layout
from app.services import block_service
from app.services import docx_export
from app.services import preview_service, render_service, workbook_layout
from app.services.rich_document import validate_doc

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
        .options(selectinload(Practice.sections)
                 .selectinload(PracticeSection.questions)
                 .selectinload(PracticeQuestion.blocks))
        .execution_options(populate_existing=True)  # 覆盖 identity map 中的过期缓存（如刚物化的块）
    )
    return result.scalar_one_or_none()


def _block_out(b: PracticeContentBlock, practice_id: str) -> dict:
    content = b.content
    if b.block_type == "image" and content:
        content = practice_service.resolve_practice_asset_urls(content, practice_id)
    elif b.block_type == "options" and content:
        try:
            content = json.loads(content)  # 存储是 JSON 字符串，出参解析为数组供前端直接用
        except (TypeError, ValueError):
            content = None
    return {"id": b.id, "block_type": b.block_type, "position": b.position,
            "content": content, "style": b.style_config}


def _question_out(practice_id: str, pq: PracticeQuestion) -> PracticeQuestionOut:
    rich_doc = None
    if pq.rich_document:
        try:
            rich_doc = json.loads(pq.rich_document)
        except (TypeError, ValueError):
            rich_doc = None
    return PracticeQuestionOut(
        id=pq.id, position=pq.position, source_question_id=pq.source_question_id,
        question_number=pq.question_number, question_type=pq.question_type,
        difficulty=pq.difficulty, score=pq.score,
        content=practice_service.resolve_practice_asset_urls(pq.content_snapshot, practice_id),
        options=pq.options_snapshot, is_modified=pq.is_modified,
        layout_config=pq.layout_config,
        rich_document=rich_doc,
        blocks=[_block_out(b, practice_id)
                for b in sorted(pq.blocks, key=lambda b: b.position)],
    )


def _practice_response(practice: Practice) -> PracticeResponse:
    sections, total = [], 0
    for s in practice.sections:
        questions = [_question_out(practice.id, pq) for pq in s.questions]
        total += len(questions)
        sections.append(PracticeSectionOut(
            id=s.id, title=s.title, section_type=s.section_type, position=s.position,
            show_title=s.show_title, start_on_new_page=s.start_on_new_page, questions=questions,
        ))
    return PracticeResponse(
        id=practice.id, title=practice.title, subtitle=practice.subtitle,
        subject=practice.subject, grade=practice.grade, status=practice.status,
        question_count=total, is_baseline=practice.is_baseline,
        created_at=practice.created_at, updated_at=practice.updated_at,
        page_config=practice.page_config, layout_document=practice.layout_document,
        sections=sections,
    )


async def _load_pq(db: AsyncSession, practice_id: str, pq_id: str) -> PracticeQuestion:
    result = await db.execute(
        select(PracticeQuestion)
        .where(PracticeQuestion.id == pq_id, PracticeQuestion.practice_id == practice_id)
        .options(selectinload(PracticeQuestion.blocks))
        .execution_options(populate_existing=True)
    )
    pq = result.scalar_one_or_none()
    if not pq:
        raise HTTPException(404, "Practice question not found")
    return pq


async def _question_payload(db: AsyncSession, pq: PracticeQuestion) -> dict:
    """块写操作统一响应：题目出参 + 块列表（直接查库取块，不依赖缓存）。"""
    blocks = (await db.execute(
        select(PracticeContentBlock)
        .where(PracticeContentBlock.practice_question_id == pq.id)
        .order_by(PracticeContentBlock.position)
    )).scalars().all()
    practice = await _get_practice_full(db, pq.practice_id)
    return {
        "question": _question_out(pq.practice_id, next(
            pq2 for s in practice.sections for pq2 in s.questions if pq2.id == pq.id)),
        "blocks": [_block_out(b, pq.practice_id) for b in blocks],
    }


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
            status=p.status, question_count=cnt.scalar() or 0, is_baseline=p.is_baseline,
            created_at=p.created_at, updated_at=p.updated_at,
        ))
    return PracticeListResponse(practices=briefs, total=len(briefs))


@router.get("/api/practices/{practice_id}", response_model=PracticeResponse)
async def get_practice(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    await workbook_layout.ensure_layout(db, practice)   # 阶段 5：惰性迁移（sections→布局），可回退
    await db.commit()
    practice = await _get_practice_full(db, practice_id)  # 提交后重载，避免 onupdate 属性过期触发同步懒加载
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


@router.put("/api/practices/{practice_id}/layout", response_model=PracticeResponse)
async def save_practice_layout(practice_id: str, req: PracticeLayoutUpdateRequest,
                               db: AsyncSession = Depends(get_db)):
    """阶段 5：保存整册编排布局（线性块序列），同步 sections 保持一致（架构 A）。"""
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    layout = await workbook_layout.sync_sections_from_layout(db, practice, req.layout)
    practice.layout_document = layout
    await db.commit()
    practice = await _get_practice_full(db, practice_id)
    return _practice_response(practice)


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


# ---------------- 内容块编辑 ----------------

class BlockCreateRequest(BaseModel):
    block_type: str
    content: Any = None
    style: dict | None = None


class BlockUpdateRequest(BaseModel):
    content: Any = None
    style: dict | None = None


class BlockReorderRequest(BaseModel):
    block_ids: list[str]


@router.get("/api/practices/{practice_id}/detail", response_model=PracticeResponse)
async def get_practice_detail(practice_id: str, db: AsyncSession = Depends(get_db)):
    """同详情，但对未物化的题目先生成内容块（懒物化）；顺带幂等重排题号。"""
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    await workbook_layout.ensure_layout(db, practice)   # 阶段 5：整册布局惰性迁移
    await db.commit()
    practice = await _get_practice_full(db, practice_id)  # 提交后重载避免过期属性
    materialized = False
    for s in practice.sections:
        for pq in s.questions:
            if not pq.blocks:
                await block_service.materialize_blocks(db, pq)
                materialized = True
    if materialized:
        await db.commit()
        practice = await _get_practice_full(db, practice_id)
    if await _migrate_option_images(db, practice_id, practice):   # 选项图引用迁入练习资产（幂等）
        await db.commit()
    await _renumber(db, practice_id)   # 来源编号（如 3/11）重排为连续 1、2、3…
    await db.commit()
    practice = await _get_practice_full(db, practice_id)
    return _practice_response(practice)


async def _migrate_option_images(db: AsyncSession, practice_id: str, practice) -> bool:
    """旧练习的选项块可能还留着 /api/ocr-assets 等外部引用，幂等迁入练习资产。"""
    changed = False
    for sec in practice.sections:
        for pq in sec.questions:
            if await practice_service.migrate_question_option_blocks(db, practice_id, pq):
                changed = True
    return changed


@router.get("/api/practices/{practice_id}/assets-list")
async def list_practice_assets(practice_id: str):
    assets_dir = practice_service.practice_assets_dir(practice_id)
    names = sorted(p.name for p in assets_dir.iterdir() if p.is_file())
    return {"assets": names}


@router.post("/api/practices/{practice_id}/assets/upload")
async def upload_practice_asset(practice_id: str, file: UploadFile = File(...)):
    """Upload a new image to the practice assets directory."""
    import uuid
    from pathlib import Path
    assets_dir = practice_service.practice_assets_dir(practice_id)
    suffix = Path(file.filename or "img.png").suffix.lower() or ".png"
    name = f"{uuid.uuid4().hex[:8]}{suffix}"
    dest = assets_dir / name
    content = await file.read()
    dest.write_bytes(content)
    return {"name": name}


@router.post("/api/practices/{practice_id}/questions/{pq_id}/blocks")
async def add_block(practice_id: str, pq_id: str, req: BlockCreateRequest,
                    db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    if req.block_type not in ("text", "image", "options", "answer_space"):
        raise HTTPException(400, f"不支持的块类型: {req.block_type}")
    content = req.content
    if req.block_type == "options" and not isinstance(content, str):
        content = json.dumps(content or [], ensure_ascii=False)  # 入参数组 → JSON 字符串落库
    existing = (await db.execute(
        select(func.max(PracticeContentBlock.position))
        .where(PracticeContentBlock.practice_question_id == pq.id)
    )).scalar()
    block = PracticeContentBlock(
        practice_question_id=pq.id, block_type=req.block_type,
        position=(existing + 1) if existing is not None else 0,
        content=content, style_config=req.style)
    db.add(block)
    await db.flush()
    await block_service.rebuild_content_from_blocks(db, pq)
    await db.commit()
    return await _question_payload(db, pq)


@router.put("/api/practices/{practice_id}/questions/{pq_id}/blocks/reorder")
async def reorder_blocks(practice_id: str, pq_id: str, req: BlockReorderRequest,
                         db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    bmap = {b.id: b for b in pq.blocks}
    for pos, bid in enumerate(req.block_ids):
        if bid in bmap:
            bmap[bid].position = pos
    await block_service.rebuild_content_from_blocks(db, pq)
    await db.commit()
    return await _question_payload(db, pq)


@router.put("/api/practices/{practice_id}/questions/{pq_id}/blocks/{block_id}")
async def update_block(practice_id: str, pq_id: str, block_id: str,
                       req: BlockUpdateRequest, db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    block = next((b for b in pq.blocks if b.id == block_id), None)
    if not block:
        raise HTTPException(404, "Block not found")
    data = req.model_dump(exclude_unset=True)
    if "content" in data:
        content = data["content"]
        if block.block_type == "options" and not isinstance(content, str):
            content = json.dumps(content or [], ensure_ascii=False)
        block.content = content
    if "style" in data:
        block.style_config = data["style"]
    await block_service.rebuild_content_from_blocks(db, pq)
    await db.commit()
    return await _question_payload(db, pq)


@router.delete("/api/practices/{practice_id}/questions/{pq_id}/blocks/{block_id}")
async def delete_block(practice_id: str, pq_id: str, block_id: str,
                       db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    block = next((b for b in pq.blocks if b.id == block_id), None)
    if not block:
        raise HTTPException(404, "Block not found")
    await db.delete(block)
    await db.flush()
    remaining = (await db.execute(
        select(PracticeContentBlock)
        .where(PracticeContentBlock.practice_question_id == pq.id)
        .order_by(PracticeContentBlock.position)
    )).scalars().all()
    for pos, b in enumerate(remaining):
        b.position = pos
    await block_service.rebuild_content_from_blocks(db, pq)
    await db.commit()
    return await _question_payload(db, pq)


class DocumentUpdateRequest(BaseModel):
    document: dict


@router.put("/api/practices/{practice_id}/questions/{pq_id}/document")
async def save_question_document(practice_id: str, pq_id: str, req: DocumentUpdateRequest,
                                 db: AsyncSession = Depends(get_db)):
    """阶段 1：保存单题富文本文档（新真源），反推重建旧块/快照（导出兼容）。"""
    pq = await _load_pq(db, practice_id, pq_id)
    errors = validate_doc(req.document)
    if errors:
        raise HTTPException(422, "文档格式非法：" + "；".join(errors[:5]))
    await block_service.apply_doc_to_question(db, pq, req.document)
    await db.commit()
    return await _question_payload(db, pq)


@router.post("/api/practices/{practice_id}/questions/{pq_id}/restore")
async def restore_question(practice_id: str, pq_id: str, db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    restored = await block_service.restore_question_from_source(db, pq)
    if not restored:
        raise HTTPException(404, "题库原题不存在或已删除，无法恢复")
    return await _question_payload(db, restored)


# ---------------- 结构编排（小节 + 题目增删移动 + 连续编号） ----------------

class SectionCreateRequest(BaseModel):
    title: str
    position: int | None = None


class SectionUpdateRequest(BaseModel):
    title: str | None = None
    show_title: bool | None = None
    start_on_new_page: bool | None = None


class SectionReorderRequest(BaseModel):
    section_ids: list[str]


class QuestionMoveRequest(BaseModel):
    target_section_id: str
    target_position: int | None = None


class QuestionMetaUpdateRequest(BaseModel):
    question_type: str | None = None
    difficulty: int | None = None
    score: float | None = None


class AddQuestionsRequest(BaseModel):
    question_ids: list[str]


@router.post("/api/practices/{practice_id}/questions/add", response_model=PracticeResponse)
async def add_questions_from_library(practice_id: str, req: AddQuestionsRequest,
                                     db: AsyncSession = Depends(get_db)):
    """已有练习继续从题库添加题目：按题型归入小节，重复跳过，连续重编号。"""
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    questions = await _load_questions_ordered(db, req.question_ids)
    if not questions:
        raise HTTPException(400, "没有可用题目：题目不存在或已删除")
    added_pqs = await practice_service.add_questions_to_practice(db, practice, questions)
    if not added_pqs:
        raise HTTPException(400, "所选题目均已在练习内")
    await db.flush()
    await _renumber(db, practice_id)
    # 同步整册布局：新题追加到 layout_document，保证整册编排/导出能显示
    await workbook_layout.append_questions_to_layout(db, practice, added_pqs)
    return await _practice_resp_after(db, practice_id)


async def _renumber(db: AsyncSession, practice_id: str):
    """按小节顺序全练习连续编号；删除已空的题型小节（空的自定义小节保留，用户可能刚新建）。"""
    sections = (await db.execute(
        select(PracticeSection)
        .where(PracticeSection.practice_id == practice_id)
        .options(selectinload(PracticeSection.questions))
        .order_by(PracticeSection.position)
        .execution_options(populate_existing=True)
    )).scalars().all()
    n = 0
    kept = []
    for s in sections:
        if not s.questions and s.section_type != "custom":
            await db.delete(s)
            continue
        for pos, q in enumerate(sorted(s.questions, key=lambda x: x.position)):
            n += 1
            q.position = pos
            q.question_number = n
        kept.append(s)
    for pos, s in enumerate(kept):
        s.position = pos


async def _get_section(db: AsyncSession, practice_id: str, section_id: str) -> PracticeSection:
    result = await db.execute(
        select(PracticeSection)
        .where(PracticeSection.id == section_id, PracticeSection.practice_id == practice_id)
        .options(selectinload(PracticeSection.questions))
        .execution_options(populate_existing=True))
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(404, "Section not found")
    return section


async def _practice_resp_after(db: AsyncSession, practice_id: str) -> PracticeResponse:
    """结构写操作后统一返回体。"""
    await db.commit()
    practice = await _get_practice_full(db, practice_id)
    return _practice_response(practice)


@router.post("/api/practices/{practice_id}/sections", response_model=PracticeResponse)
async def add_section(practice_id: str, req: SectionCreateRequest,
                      db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    section = PracticeSection(
        practice_id=practice_id, title=req.title, section_type="custom",
        position=req.position if req.position is not None else len(practice.sections))
    db.add(section)
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/sections/reorder", response_model=PracticeResponse)
async def reorder_sections(practice_id: str, req: SectionReorderRequest,
                           db: AsyncSession = Depends(get_db)):
    sections = (await db.execute(
        select(PracticeSection).where(PracticeSection.practice_id == practice_id)
    )).scalars().all()
    smap = {s.id: s for s in sections}
    for pos, sid in enumerate(req.section_ids):
        if sid in smap:
            smap[sid].position = pos
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/sections/{section_id}", response_model=PracticeResponse)
async def update_section(practice_id: str, section_id: str, req: SectionUpdateRequest,
                         db: AsyncSession = Depends(get_db)):
    section = await _get_section(db, practice_id, section_id)
    for k, v in req.model_dump(exclude_unset=True).items():
        setattr(section, k, v)
    return await _practice_resp_after(db, practice_id)


@router.delete("/api/practices/{practice_id}/sections/{section_id}", response_model=PracticeResponse)
async def delete_section(practice_id: str, section_id: str, db: AsyncSession = Depends(get_db)):
    section = await _get_section(db, practice_id, section_id)
    if section.questions:
        raise HTTPException(400, "小节内仍有题目，无法删除；请先移走或删除题目")
    await db.delete(section)
    await _renumber(db, practice_id)
    return await _practice_resp_after(db, practice_id)


@router.delete("/api/practices/{practice_id}/questions/{pq_id}", response_model=PracticeResponse)
async def delete_question(practice_id: str, pq_id: str, db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    await db.delete(pq)   # 块级联删除（外键 ondelete=CASCADE + ORM delete-orphan）
    await db.flush()
    # 同步移除整册布局中该题的引用块，避免画布残留「题目已被删除」占位
    practice = await _get_practice_full(db, practice_id)
    if practice and practice.layout_document:
        layout = [b for b in practice.layout_document
                  if not (b.get("type") == "question_ref" and b.get("question_id") == pq_id)]
        # 移除已变空的子标题（其后紧跟下一子标题或结尾 → 无任何内容），
        # 因为对应空题型 section 会被 _renumber 删除，subtitle 不应残留
        out = []
        for i, b in enumerate(layout):
            if b.get("type") == "subtitle":
                nxt = layout[i + 1] if i + 1 < len(layout) else None
                if nxt is None or nxt.get("type") == "subtitle":
                    continue
            out.append(b)
        if len(out) != len(layout):
            practice.layout_document = out
            await db.flush()
    await _renumber(db, practice_id)
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/questions/{pq_id}/move", response_model=PracticeResponse)
async def move_question(practice_id: str, pq_id: str, req: QuestionMoveRequest,
                        db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    target = await _get_section(db, practice_id, req.target_section_id)
    positions = [q.position for q in target.questions if q.id != pq.id]
    pq.section_id = target.id
    pq.position = req.target_position if req.target_position is not None \
        else (max(positions, default=-1) + 1)
    # 不改目标小节的 section_type/标题；题型不一致时由一键整理结构处理
    await db.flush()
    await _renumber(db, practice_id)
    return await _practice_resp_after(db, practice_id)


@router.put("/api/practices/{practice_id}/questions/{pq_id}", response_model=PracticeResponse)
async def update_question_meta(practice_id: str, pq_id: str, req: QuestionMetaUpdateRequest,
                               db: AsyncSession = Depends(get_db)):
    pq = await _load_pq(db, practice_id, pq_id)
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(pq, k, v)
    if data:
        pq.is_modified = True  # 元数据修改也计入已修改；小节名不随之改变
    return await _practice_resp_after(db, practice_id)


# ---------------- 一键排版 ----------------

@router.post("/api/practices/{practice_id}/regroup/preview")
async def regroup_preview(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    return await block_service.plan_regroup(practice)


@router.post("/api/practices/{practice_id}/regroup/apply", response_model=PracticeResponse)
async def regroup_apply(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    await block_service.apply_regroup(db, practice)
    await _renumber(db, practice_id)
    await db.commit()
    practice = await _get_practice_full(db, practice_id)
    return _practice_response(practice)


@router.post("/api/practices/{practice_id}/layout/unify")
async def layout_unify(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    # 先确保每题已物化块，再统一排版，否则未进过编辑器的题不会被处理
    materialized = False
    for s in practice.sections:
        for pq in s.questions:
            if not pq.blocks:
                await block_service.materialize_blocks(db, pq)
                materialized = True
    if materialized:
        await db.commit()
        practice = await _get_practice_full(db, practice_id)
    n = await block_service.unify_layout(db, practice)
    return {"adjusted": n}


# ---------------- 预览与导出（阶段三） ----------------

async def _load_for_render(db: AsyncSession, practice_id: str) -> Practice:
    """渲染专用加载：懒物化块 + 三层 selectinload + populate_existing。"""
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
    changed = False
    for sec in practice.sections:
        for pq in sec.questions:
            if not pq.blocks:
                await block_service.materialize_blocks(db, pq)
                changed = True
    if changed:
        await db.commit()   # materialize 只 flush；提交后必须重取（缓存已过期）
        practice = await _get_practice_full(db, practice_id)
    if await _migrate_option_images(db, practice_id, practice):
        await db.commit()
        practice = await _get_practice_full(db, practice_id)
    await _renumber(db, practice_id)   # 导出/预览前保证题号连续（幂等）
    await db.commit()
    practice = await _get_practice_full(db, practice_id)
    return practice


@router.post("/api/practices/{practice_id}/render", response_model=PreviewRenderResponse)
async def render_practice_preview(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _load_for_render(db, practice_id)
    html = render_service.build_practice_html(practice, practice_id)
    settings = render_service.render_settings(practice)
    _, sha, pages = await render_service.ensure_preview_pdf(practice_id, html, settings)
    return PreviewRenderResponse(pages=pages, sha=sha)


@router.get("/api/practices/{practice_id}/preview/page/{index}")
async def preview_page_image(practice_id: str, index: int, scale: float = 2.0):
    pdir = practice_service.practices_root() / practice_id
    pdf_path, meta_path = pdir / "preview.pdf", pdir / "preview_meta.json"
    if not pdf_path.exists() or not meta_path.exists():
        raise HTTPException(404, "请先调用 POST /render 生成预览")
    try:
        png = preview_service.page_png(pdf_path, index, min(max(scale, 0.5), 4.0))
    except IndexError:
        raise HTTPException(404, "页码超出范围")
    return Response(content=png, media_type="image/png")


def _export_filename(title: str, ext: str) -> str:
    clean = re.sub(r'[\\/:*?"<>|]', "_", title or "练习")
    return f"{clean}.{ext}"


@router.get("/api/practices/{practice_id}/export/docx")
async def export_docx(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _load_for_render(db, practice_id)
    data, degraded = await asyncio.to_thread(docx_export.build_docx, practice, practice_id)
    practice.status = "exported"
    await db.commit()
    headers = {"Content-Disposition":
               f"attachment; filename*=utf-8''{quote(_export_filename(practice.title, 'docx'))}"}
    if degraded:   # 公式降级为图片清单（URL 编码，前端解码后明确提示）
        headers["X-Formula-Degraded"] = quote("; ".join(degraded), safe="")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@router.get("/api/practices/{practice_id}/export/pdf")
async def export_pdf(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _load_for_render(db, practice_id)
    html = render_service.build_practice_html(practice, practice_id)
    settings = render_service.render_settings(practice)
    pdf_path, _, _ = await render_service.ensure_preview_pdf(practice_id, html, settings)
    practice.status = "exported"
    await db.commit()
    return StreamingResponse(
        io.BytesIO(pdf_path.read_bytes()),
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f"attachment; filename*=utf-8''{quote(_export_filename(practice.title, 'pdf'))}"},
    )
