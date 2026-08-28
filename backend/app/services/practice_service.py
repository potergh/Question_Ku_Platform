"""Practice service — basket helpers, snapshot creation, asset copying."""

import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import Question, Source
from app.models.basket import SelectionBasket
from app.models.practice import Practice, PracticeSection, PracticeQuestion
from app.utils.question_types import map_question_type

ASSET_RE = re.compile(r"asset://([^\s\)]+)")

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


async def create_practice_from_questions(
    db: AsyncSession, title: str, subtitle: str | None, subject: str | None,
    grade: str | None, questions: list,
) -> Practice:
    """按题型分组创建练习 + 小节 + 题目快照。"""
    practice = Practice(title=title, subtitle=subtitle, subject=subject, grade=grade)
    db.add(practice)
    await db.flush()

    groups: dict[str, list] = {}
    for q in questions:
        groups.setdefault(map_question_type(q.question_type), []).append(q)

    ordered = [t for t in SECTION_TYPE_ORDER if t in groups] + [
        t for t in groups if t not in SECTION_TYPE_ORDER
    ]
    for pos, zh_type in enumerate(ordered):
        section = PracticeSection(
            practice_id=practice.id, title=zh_type, section_type=zh_type, position=pos,
        )
        db.add(section)
        await db.flush()
        for i, q in enumerate(groups[zh_type]):
            await snapshot_question(db, practice, section, q, i)

    await db.commit()
    result = await db.execute(
        select(Practice)
        .where(Practice.id == practice.id)
        .options(selectinload(Practice.sections).selectinload(PracticeSection.questions))
    )
    return result.scalar_one()
