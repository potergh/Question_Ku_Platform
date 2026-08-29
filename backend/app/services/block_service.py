"""Block service — materialize question content into editable blocks and rebuild."""

import json
from pathlib import Path

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Question, Source
from app.models.practice import PracticeContentBlock, PracticeQuestion
from app.services.practice_service import (
    ASSET_RE,
    _copy_referenced_assets,
    practice_assets_dir,
)

# 题型英文名 → 默认答题留白行数（决策 6：默认值由题型决定，单题可覆盖）
DEFAULT_ANSWER_SPACE = {
    "single_choice": 0, "multiple_choice": 0,
    "fill_blank": 2, "experiment": 4, "calculation": 8,
    "short_answer": 6, "essay": 6, "comprehensive": 6, "unknown": 4,
}

# 一键统一排版时应用到未定制图片块的默认样式
IMAGE_DEFAULT_STYLE = {"align": "center", "width": "fit"}


async def materialize_blocks(db: AsyncSession, pq: PracticeQuestion) -> list[PracticeContentBlock]:
    """把快照内容分解为内容块（幂等：已有块直接返回）。
    只 flush 不 commit，由调用方负责提交，避免 commit 使 pq.blocks 关系过期。"""
    existing = (await db.execute(
        select(PracticeContentBlock)
        .where(PracticeContentBlock.practice_question_id == pq.id)
        .order_by(PracticeContentBlock.position)
    )).scalars().all()
    if existing:
        return list(existing)

    blocks: list[PracticeContentBlock] = []

    def add(block_type: str, content, style: dict | None = None):
        blocks.append(PracticeContentBlock(
            practice_question_id=pq.id, block_type=block_type,
            position=len(blocks), content=content, style_config=style,
        ))

    content = pq.content_snapshot or ""
    last = 0
    for m in ASSET_RE.finditer(content):
        pre = content[last:m.start()].strip()
        if pre:
            add("text", pre)
        add("image", f"asset://{m.group(1)}", style=dict(IMAGE_DEFAULT_STYLE))  # 默认居中/适应（规格 9.2）
        last = m.end()
    tail = content[last:].strip()
    if tail:
        add("text", tail)
    if pq.options_snapshot:
        add("options", json.dumps(pq.options_snapshot, ensure_ascii=False))
    add("answer_space", None, {"rows": DEFAULT_ANSWER_SPACE.get(pq.question_type, 4)})

    db.add_all(blocks)
    await db.flush()
    for b in blocks:
        await db.refresh(b)
    return blocks


async def rebuild_content_from_blocks(db: AsyncSession, pq: PracticeQuestion) -> str:
    """按块重建 content_snapshot（图片内联），并回写选项快照、标记已修改。
    直接查库取块，不依赖 relationship 缓存（避免 identity map 状态过期问题）。"""
    blocks = (await db.execute(
        select(PracticeContentBlock)
        .where(PracticeContentBlock.practice_question_id == pq.id)
        .order_by(PracticeContentBlock.position)
    )).scalars().all()
    parts: list[str] = []
    options = None
    for b in blocks:
        if b.block_type == "text" and (b.content or "").strip():
            parts.append(b.content.strip())
        elif b.block_type == "image" and b.content:
            parts.append(f"![图]({b.content})")
        elif b.block_type == "options":
            # options 块的 content 是选项数组的 JSON 字符串；空串 = 删除选项块语义，不回写
            if (b.content or "").strip():
                options = json.loads(b.content)
    pq.content_snapshot = "\n\n".join(parts)
    if options is not None:
        pq.options_snapshot = options
    pq.is_modified = True
    return pq.content_snapshot


async def restore_question_from_source(db: AsyncSession, pq: PracticeQuestion) -> PracticeQuestion | None:
    """恢复为题库原题版本：重新快照内容与图片，重建内容块。原题不存在返回 None。"""
    if not pq.source_question_id:
        return None
    source_q = await db.get(Question, pq.source_question_id)
    if not source_q or source_q.is_deleted:
        return None

    source = await db.get(Source, source_q.source_id)
    ocr_dir = Path(source.ocr_result_path) if source and source.ocr_result_path else None
    content = _copy_referenced_assets(
        source_q.content, ocr_dir, practice_assets_dir(pq.practice_id))

    pq.question_number = source_q.question_number
    pq.question_type = source_q.question_type
    pq.subject = source_q.subject
    pq.difficulty = source_q.difficulty
    pq.score = source_q.score
    pq.content_snapshot = content
    pq.options_snapshot = source_q.options
    pq.answer_snapshot = source_q.answer
    pq.explanation_snapshot = source_q.explanation
    pq.source_version = source_q.updated_at
    pq.is_modified = False
    pq.layout_config = None

    await db.execute(delete(PracticeContentBlock)
                     .where(PracticeContentBlock.practice_question_id == pq.id))
    await db.commit()
    await db.refresh(pq)
    await materialize_blocks(db, pq)
    await db.commit()
    # 重新加载并预加载块，避免返回后访问 relationship 触发懒加载（MissingGreenlet）
    result = await db.execute(
        select(PracticeQuestion)
        .where(PracticeQuestion.id == pq.id)
        .options(selectinload(PracticeQuestion.blocks))
    )
    return result.scalar_one()
