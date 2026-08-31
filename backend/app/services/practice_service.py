"""Practice service — basket helpers, snapshot creation, asset copying."""

import json
import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Question, Source
from app.models.basket import SelectionBasket
from app.models.practice import Practice, PracticeSection, PracticeQuestion
from app.services.rich_document import sync_rich_document
from app.utils.question_types import map_question_type

ASSET_RE = re.compile(r"asset://([^\s\)]+)")

# 阶段 6：新练习默认页眉页脚（标题页眉 + 居中页码）
DEFAULT_HEADER = {
    "enabled": True,
    "left": "", "center": "{title}", "right": "",
    "font_size": 9, "distance": 8, "line": False,
    "first_page_different": True, "first_hidden": True,
}
DEFAULT_FOOTER = {
    "enabled": True,
    "left": "", "center": "{page} / {total}", "right": "",
    "font_size": 9, "distance": 8, "line": False,
    "first_hidden": False,
}


def default_page_config() -> dict:
    """新练习默认页面配置（含阶段 6 页眉页脚默认）。"""
    return {
        "show_info_bar": True, "margin_preset": "normal", "show_page_number": True,
        "show_score": False, "show_total_score": True,
        "default_style": {"font_family": "宋体", "font_size": 10.5, "line_height": 1.7},
        "orientation": "portrait",
        "variables": {"school": "", "teacher": ""},
        "header": DEFAULT_HEADER,
        "footer": DEFAULT_FOOTER,
    }


# 小节按题型生成时的固定顺序
SECTION_TYPE_ORDER = [
    "选择题", "多选题", "填空题", "实验题", "计算题",
    "解答题", "简答题", "论述题", "综合题", "未知题型",
]


def practices_root() -> Path:
    root = settings.data_dir / "practices"
    root.mkdir(parents=True, exist_ok=True)
    return root


def practice_assets_dir(practice_id: str) -> Path:
    d = practices_root() / practice_id / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def get_or_create_basket(db: AsyncSession) -> SelectionBasket:
    """V1 全局唯一选题池，懒创建。"""
    result = await db.execute(select(SelectionBasket).order_by(SelectionBasket.created_at).limit(1))
    basket = result.scalar_one_or_none()
    if not basket:
        basket = SelectionBasket()
        db.add(basket)
        await db.commit()
        await db.refresh(basket)
    return basket


def resolve_practice_asset_urls(content: str | None, practice_id: str) -> str | None:
    """asset://practice/xxx → /api/practices/{id}/assets/xxx"""
    if not content:
        return content
    return re.sub(
        r"asset://practice/([^\s\)]+)",
        rf"/api/practices/{practice_id}/assets/\1",
        content,
    )


async def snapshot_question(
    db: AsyncSession, practice: Practice, section: PracticeSection,
    question: Question, position: int,
) -> PracticeQuestion:
    """创建题目快照，并将引用图片复制到练习目录。"""
    source = await db.get(Source, question.source_id)
    ocr_dir = Path(source.ocr_result_path) if source and source.ocr_result_path else None
    content = _copy_referenced_assets(question.content, ocr_dir, practice_assets_dir(practice.id))
    # /api/ocr-assets/… 形式的引用也迁入练习资产（上面只处理 asset://），
    # 否则预览/导出时图片位置会显示 Markdown 原文
    content = await migrate_option_refs(db, practice.id, content, ocr_dir)

    pq = PracticeQuestion(
        practice_id=practice.id,
        section_id=section.id,
        source_question_id=question.id,
        position=position,
        question_number=question.question_number,
        question_type=question.question_type,
        subject=question.subject,
        difficulty=question.difficulty,
        score=question.score,
        content_snapshot=content,
        options_snapshot=question.options,
        answer_snapshot=question.answer,
        explanation_snapshot=question.explanation,
        source_version=question.updated_at,
    )
    db.add(pq)
    await db.flush()
    await db.refresh(pq)
    # 选项中的图片引用同样复制进练习资产（否则导出/预览时选项图显示为 Markdown 文本）
    if question.options:
        new_opts = []
        for o in question.options:
            c = await migrate_option_refs(db, practice.id, o.get("content"), ocr_dir)
            new_opts.append({**o, "content": c} if c != o.get("content") else o)
        pq.options_snapshot = new_opts
    return pq


def _copy_referenced_assets(content: str | None, ocr_dir: Path | None, assets_dir: Path) -> str | None:
    """把内容引用的图片复制到练习资产目录，并改写为 asset://practice/<name>。"""
    if not content or not ocr_dir:
        return content

    def _replace(m):
        rel = re.sub(r"^figures/figures/", "figures/", m.group(1))
        if rel.startswith("practice/"):
            return m.group(0)  # 已是练习内资产（复制练习等场景）
        src = ocr_dir / rel
        if not src.exists():
            return m.group(0)  # 文件缺失，保留原引用
        name = f"{uuid.uuid4().hex[:8]}_{src.name}"
        shutil.copy2(src, assets_dir / name)
        return f"asset://practice/{name}"

    return ASSET_RE.sub(_replace, content)


# 选项/文本中的图片引用（含 Markdown 包装；替换只动内层引用，包装保留）
_MD_IMG_REF_RE = re.compile(
    r"(!\[[^\]]*\]\()?(/api/ocr-assets/[^\s\)]+|asset://[^\s\)]+)(\))?")


async def migrate_option_refs(db: AsyncSession, practice_id: str, content: str | None,
                              ocr_dir: Path | None = None) -> str | None:
    """把选项引用的外部图片（/api/ocr-assets/… 或 asset://…）复制到练习资产并改写，
    使练习自包含（源文件删除后仍可导出）。幂等：已是 practice 资产的引用不动。
    ocr_dir：裸 asset:// 引用的解析根（未传则该形式保留原样）。"""
    if not content or ("/api/ocr-assets/" not in content and "asset://" not in content):
        return content
    assets_dir = practice_assets_dir(practice_id)
    ocr_cache: dict[str, Path | None] = {}

    async def _ocr_dir(source_id: str) -> Path | None:
        if source_id not in ocr_cache:
            source = await db.get(Source, source_id)
            ocr_cache[source_id] = (Path(source.ocr_result_path)
                                    if source and source.ocr_result_path else None)
        return ocr_cache[source_id]

    async def _replace(m):
        pre, ref, post = m.group(1) or "", m.group(2), m.group(3) or ""
        if ref.startswith("/api/ocr-assets/"):
            parts = ref.removeprefix("/api/ocr-assets/").split("/", 1)
            if len(parts) != 2:
                return m.group(0)
            ocr_root = await _ocr_dir(parts[0])
            src = ocr_root / parts[1] if ocr_root else None
        else:
            rel = re.sub(r"^figures/figures/", "figures/", ref.removeprefix("asset://"))
            if rel.startswith("practice/"):
                return m.group(0)   # 已迁移（幂等）
            src = ocr_dir / rel if ocr_dir else None
        if not src or not src.exists():
            return m.group(0)   # 文件缺失，保留原引用（导出时显示文字）
        name = f"{uuid.uuid4().hex[:8]}_{src.name}"
        shutil.copy2(src, assets_dir / name)
        return f"{pre}asset://practice/{name}{post}"

    # 逐段处理（替换函数为 async，re.sub 不支持，手动切分）
    out: list[str] = []
    last = 0
    for m in _MD_IMG_REF_RE.finditer(content):
        out.append(content[last:m.start()])
        out.append(await _replace(m))
        last = m.end()
    out.append(content[last:])
    return "".join(out)


async def migrate_question_option_blocks(db: AsyncSession, practice_id: str, pq) -> bool:
    """幂等迁移题目选项块中的外部图片引用；返回是否有变更（调用方负责 commit）。"""
    changed = False
    ocr_dir: Path | None = None
    if pq.source_question_id:
        q = await db.get(Question, pq.source_question_id)
        source = await db.get(Source, q.source_id) if q else None
        if source and source.ocr_result_path:
            ocr_dir = Path(source.ocr_result_path)
    for b in pq.blocks:
        if b.block_type != "options":
            continue
        try:
            opts = json.loads(b.content) if b.content else []
        except (TypeError, json.JSONDecodeError):
            continue
        new_opts, opt_changed = [], False
        for o in opts:
            c = await migrate_option_refs(db, practice_id, o.get("content"), ocr_dir)
            if c != o.get("content"):
                o = dict(o)
                o["content"] = c
                opt_changed = True
            new_opts.append(o)
        if opt_changed:
            b.content = json.dumps(new_opts, ensure_ascii=False)
            changed = True
    if changed:
        # 选项块变更后同步选项快照与新富文本文档，避免块/快照/文档不一致
        opts = next((json.loads(b.content) for b in pq.blocks if b.block_type == "options"), None)
        if opts is not None:
            pq.options_snapshot = opts
        sync_rich_document(pq, sorted(pq.blocks, key=lambda b: b.position))
    return changed


async def create_practice_from_questions(
    db: AsyncSession, title: str, subtitle: str | None, subject: str | None,
    grade: str | None, questions: list,
) -> Practice:
    """按题型分组创建练习 + 小节 + 题目快照。新建练习直接进入新文档结构（native）。"""
    practice = Practice(title=title, subtitle=subtitle, subject=subject, grade=grade,
                        migration_status="native", page_config=default_page_config())
    db.add(practice)
    await db.flush()

    groups: dict[str, list] = {}
    for q in questions:
        groups.setdefault(map_question_type(q.question_type), []).append(q)

    ordered = [t for t in SECTION_TYPE_ORDER if t in groups] + [
        t for t in groups if t not in SECTION_TYPE_ORDER
    ]
    n = 0   # 创建时即连续编号（不保留题库原卷号；用户决策 2026-08-30）
    for pos, zh_type in enumerate(ordered):
        section = PracticeSection(
            practice_id=practice.id, title=zh_type, section_type=zh_type, position=pos,
        )
        db.add(section)
        await db.flush()
        for i, q in enumerate(groups[zh_type]):
            pq = await snapshot_question(db, practice, section, q, i)
            n += 1
            pq.question_number = n

    await db.commit()
    result = await db.execute(
        select(Practice)
        .where(Practice.id == practice.id)
        .options(selectinload(Practice.sections).selectinload(PracticeSection.questions))
    )
    return result.scalar_one()


async def add_questions_to_practice(
    db: AsyncSession, practice: Practice, questions: list,
) -> int:
    """已有练习继续从题库添加：按题型归入对应小节（缺则新建），已在练习内的跳过。返回实际添加数。"""
    existing = {pq.source_question_id for s in practice.sections for pq in s.questions}
    added = 0
    for q in questions:
        if q.id in existing:
            continue
        zh_type = map_question_type(q.question_type)
        section = next((s for s in practice.sections if s.section_type == zh_type), None)
        if section is None:
            section = PracticeSection(
                practice_id=practice.id, title=zh_type, section_type=zh_type,
                position=max((s.position for s in practice.sections), default=-1) + 1,
            )
            db.add(section)
            await db.flush()
            practice.sections.append(section)
        # 新建小节的 questions 关系未预加载，显式查库取末尾位置（避免异步懒加载）
        max_pos = (await db.execute(
            select(func.max(PracticeQuestion.position))
            .where(PracticeQuestion.section_id == section.id)
        )).scalar()
        position = (max_pos if max_pos is not None else -1) + 1
        await snapshot_question(db, practice, section, q, position)
        existing.add(q.id)
        added += 1
    return added
