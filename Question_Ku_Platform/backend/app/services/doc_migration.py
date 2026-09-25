"""阶段 0 Task 0.5：旧练习 → 新富文本文档结构迁移服务。

规则（与计划 2026-08-30-practice-editor-feature-00-baseline.md 对应）：
- 只读旧字段生成新文档（rich_document），旧字段保持原样，支持回退读取。
- 幂等：重复执行从旧字段重新生成，不重复生成节点、不产生重复内容。
- 单份练习失败不影响其他练习：失败标记在练习级（migration_status='failed' + note）。
- 无法识别的内容保留原文并记录警告（不阻止迁移）。
- 只 flush 不 commit，提交留给调用方（脚本/测试控制事务边界）。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.practice import Practice, PracticeContentBlock, PracticeQuestion, PracticeSection
from app.services import block_service
from app.services.rich_document import (
    doc_from_blocks,
    doc_from_snapshot,
    serialize,
    sync_rich_document,
    DOC_SCHEMA_VERSION,
)


async def _ordered_blocks(db: AsyncSession, pq_id: str) -> list[PracticeContentBlock]:
    return list((await db.execute(
        select(PracticeContentBlock)
        .where(PracticeContentBlock.practice_question_id == pq_id)
        .order_by(PracticeContentBlock.position)
    )).scalars().all())


async def load_practice_for_migration(db: AsyncSession, practice_id: str) -> Practice | None:
    result = await db.execute(
        select(Practice).where(Practice.id == practice_id)
        .options(selectinload_sections())
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


def selectinload_sections():
    from sqlalchemy.orm import selectinload
    return (selectinload(Practice.sections)
            .selectinload(PracticeSection.questions))


async def migrate_practice(db: AsyncSession, practice: Practice) -> dict:
    """迁移单份练习（写入新字段）。返回 {questions, warnings}。"""
    warnings: list[str] = []
    count = 0
    for section in sorted(practice.sections, key=lambda s: s.position):
        for pq in sorted(section.questions, key=lambda q: q.position):
            blocks = await _ordered_blocks(db, pq.id)
            if not blocks:
                blocks = await block_service.materialize_blocks(db, pq)
            w = sync_rich_document(pq, blocks)
            warnings.extend(f"题目{pq.id} #{pq.question_number}: {x}" for x in w)
            count += 1
    practice.migration_status = "done"
    practice.migration_note = "；".join(warnings[:50]) if warnings else None
    practice.migrated_at = datetime.now()
    return {"questions": count, "warnings": warnings}


async def dry_run_practice(db: AsyncSession, practice: Practice) -> dict:
    """试运行：只做转换与统计，不落库（调用方不得 commit）。
    无块的题目不物化，直接走快照回退路径统计。"""
    warnings: list[str] = []
    count = 0
    empty_content = 0
    for section in sorted(practice.sections, key=lambda s: s.position):
        for pq in sorted(section.questions, key=lambda q: q.position):
            blocks = await _ordered_blocks(db, pq.id)
            ctx = f"题目{pq.id} #{pq.question_number}"
            if blocks:
                w: list[str] = []
                doc_from_blocks(blocks, w)
                warnings.extend(f"{ctx}: {x}" for x in w)
            else:
                if not (pq.content_snapshot or "").strip():
                    empty_content += 1
                    warnings.append(f"{ctx}: 题干为空")
                w = []
                doc_from_snapshot(pq.content_snapshot, pq.options_snapshot, w)
                warnings.extend(f"{ctx}: {x}" for x in w)
            count += 1
    return {"questions": count, "warnings": warnings, "empty_content": empty_content}
