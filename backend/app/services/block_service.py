"""Block service — materialize question content into editable blocks and rebuild."""

import json
import re
from pathlib import Path

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Question, Source
from app.models.practice import Practice, PracticeContentBlock, PracticeQuestion, PracticeSection
from app.services.practice_service import (
    ASSET_RE,
    SECTION_TYPE_ORDER,
    _copy_referenced_assets,
    migrate_option_refs,
    practice_assets_dir,
)
from app.services.rich_document import blocks_from_doc, serialize, sync_rich_document
from app.utils.question_types import map_question_type

# 题型英文名 → 默认答题留白行数（决策 6：默认值由题型决定，单题可覆盖）
DEFAULT_ANSWER_SPACE = {
    "single_choice": 0, "multiple_choice": 0,
    "fill_blank": 2, "experiment": 4, "calculation": 8,
    "short_answer": 6, "essay": 6, "comprehensive": 6, "unknown": 4,
}

# 一键统一排版时应用到未定制图片块的默认样式
IMAGE_DEFAULT_STYLE = {"align": "center", "width": "fit"}


# 图片 Markdown 包装（重建快照时会写回）：物化前剔除，避免 `![图](`/`)` 残留为文字块、隔开相邻图片
MD_IMG_RE = re.compile(r"!\[[^\]]*\]\((asset://[^\s\)]+)\)")


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

    # 剔除后补空格：避免相邻裸引用被 ASSET_RE（[^\s\)]+）吞成同一个图片块
    content = MD_IMG_RE.sub(r" \1 ", pq.content_snapshot or "")
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
    sync_rich_document(pq, blocks)   # 阶段 0 双写桥：物化同时生成新富文本文档（不动旧字段）
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
    sync_rich_document(pq, blocks)   # 阶段 0 双写桥：块变更后同步新富文本文档（只写新字段）
    return pq.content_snapshot


async def apply_doc_to_question(db: AsyncSession, pq: PracticeQuestion, doc: dict) -> None:
    """阶段 1 反向双写：编辑器文档为新真源，重建旧块/快照（只 flush，提交留给调用方）。
    rich_document 存编辑器原文（保留 marks 等格式），旧字段由文档反推（导出兼容）。"""
    await db.execute(delete(PracticeContentBlock)
                     .where(PracticeContentBlock.practice_question_id == pq.id))
    await db.flush()
    blocks = [PracticeContentBlock(
        practice_question_id=pq.id, block_type=b["block_type"], position=pos,
        content=b["content"], style_config=b["style"],
    ) for pos, b in enumerate(blocks_from_doc(doc))]
    db.add_all(blocks)
    await db.flush()
    for b in blocks:
        await db.refresh(b)
    await rebuild_content_from_blocks(db, pq)   # 内部会由块同步 rich_document（旧→新方向）
    # 再以编辑器文档覆盖：保留 marks 等块表达不了的格式（新真源）
    pq.rich_document = serialize(doc)
    pq.doc_version = 1


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
    # 选项引用同样迁入练习资产（与创建快照一致）
    new_opts = []
    for o in (source_q.options or []):
        c = await migrate_option_refs(db, pq.practice_id, o.get("content"), ocr_dir)
        new_opts.append({**o, "content": c} if c != o.get("content") else o)
    pq.options_snapshot = new_opts or source_q.options
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


# ---------------- 一键排版 ----------------

async def plan_regroup(practice: Practice) -> dict:
    """干跑整理结构：返回变化描述（规格 9.3 执行前展示变化）。"""
    changes: list[str] = []
    groups: dict[str, list] = {}
    for s in sorted(practice.sections, key=lambda x: x.position):
        for q in sorted(s.questions, key=lambda x: x.position):
            zh = map_question_type(q.question_type)
            groups.setdefault(zh, []).append((s, q))
    expected = [t for t in SECTION_TYPE_ORDER if t in groups]
    # 当前非 custom 小节序列（去重保序）
    current: list[str] = []
    for s in sorted(practice.sections, key=lambda x: x.position):
        if s.section_type != "custom" and s.title not in current:
            current.append(s.title)
    if current != expected:
        changes.append("题型小节将按固定顺序重排：" + "、".join(expected))
    for zh, qs in groups.items():
        sec_of = {s.title for s, _ in qs}
        if len(sec_of) > 1:
            changes.append(f"《{zh}》的题目分散在多个小节，将合并")
        for s, q in qs:
            if s.section_type == "custom":
                changes.append(f"题目（编号{q.question_number}）将从自定义小节《{s.title}》移入《{zh}》")
    return {"changes": changes, "applies": bool(changes)}


async def apply_regroup(db: AsyncSession, practice: Practice):
    """按题型重新分组；自定义小节整体保留并置底；题目保持全局原顺序。
    顺序：先建新小节并迁移题目，再删旧小节，避免 delete-orphan 级联误删题目。"""
    ordered_qs = [q for s in sorted(practice.sections, key=lambda x: x.position)
                  for q in sorted(s.questions, key=lambda x: x.position)]
    customs = [s for s in sorted(practice.sections, key=lambda x: x.position)
               if s.section_type == "custom"]
    old_sections = [s for s in practice.sections if s.section_type != "custom"]

    groups: dict[str, list] = {}
    for q in ordered_qs:
        groups.setdefault(map_question_type(q.question_type), []).append(q)

    new_sections: list[PracticeSection] = []
    pos = 0
    for zh in [t for t in SECTION_TYPE_ORDER if t in groups]:
        section = PracticeSection(practice_id=practice.id, title=zh,
                                  section_type=zh, position=pos)
        db.add(section)
        await db.flush()
        await db.refresh(section, attribute_names=["questions"])  # 初始化集合，避免 append 触发懒加载
        for q in groups[zh]:
            # 用集合 append（而非直接赋 section_id）：确保题目先入新小节集合，
            # 再从旧集合移除，避免中途被标记为 orphan 而级联删除
            section.questions.append(q)
        new_sections.append(section)
        pos += 1
    await db.flush()

    for s in old_sections:
        await db.delete(s)  # 此时题目已全部迁出，级联安全
    for s in customs:
        s.position = pos
        pos += 1
    await db.flush()
    await db.commit()


async def unify_layout(db: AsyncSession, practice: Practice) -> int:
    """统一排版：只覆盖未定制（style_config 为空）的块样式；不动顺序。"""
    adjusted = 0
    qmap = {}
    for s in practice.sections:
        for q in s.questions:
            qmap[q.id] = q
    blocks = (await db.execute(
        select(PracticeContentBlock).where(
            PracticeContentBlock.practice_question_id.in_(list(qmap.keys())))
    )).scalars().all()
    for b in blocks:
        if b.style_config:
            continue  # 用户已定制，不覆盖（规格 9.3）
        if b.block_type == "image":
            b.style_config = dict(IMAGE_DEFAULT_STYLE)
            adjusted += 1
        elif b.block_type == "answer_space":
            q = qmap[b.practice_question_id]
            if q.question_type in ("single_choice", "multiple_choice"):
                continue
            b.style_config = {"rows": DEFAULT_ANSWER_SPACE.get(q.question_type, 4)}
            adjusted += 1
    await db.commit()
    return adjusted
