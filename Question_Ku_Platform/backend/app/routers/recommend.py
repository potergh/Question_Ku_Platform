"""智能选题推荐：规则打分（不依赖 LLM）。

按 学科/年级/考点标签/难度档位/题型 过滤题库，结合
「标签命中数 + 难度/题型匹配 + 来源可信 + 题面完整度」打分排序，
默认排除选题池已有与已入练习的题目，返回 count×2 条推荐及推荐理由。
"""

import random
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import PracticeQuestion, Question, SelectionBasketItem, Source, Tag
from app.utils.question_types import QUESTION_TYPE_MAP

router = APIRouter()

# 难度档位 -> 题库 difficulty 值域（1-5）
DIFFICULTY_BANDS = {
    "easy": [1, 2],
    "medium": [3],
    "hard": [4, 5],
}
DIFFICULTY_ZH = {1: "易", 2: "较易", 3: "中等", 4: "较难", 5: "难"}


class RecommendRequest(BaseModel):
    subject: str | None = None
    grade: str | None = None
    tag_ids: list[str] = []
    difficulty_bands: list[str] = []  # easy / medium / hard
    question_types: list[str] = []  # 中文题型
    count: int = 10
    exclude_used: bool = True


class RecommendItem(BaseModel):
    id: str
    question_type: str | None = None
    subject: str | None = None
    difficulty: int | None = None
    grade: str | None = None
    content: str = ""
    tags: list[str] = []
    source_name: str | None = None
    reason: str = ""


class RecommendResponse(BaseModel):
    items: list[RecommendItem] = []
    total_candidates: int = 0


def _strip_markdown(text: str | None, limit: int = 80) -> str:
    """题干摘要：去公式/OCR 残留标记/链接，折叠空白，截断。"""
    if not text:
        return ""
    t = text
    t = t.replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "")
    # OCR 图片残留标记：[figure]path / [img]path / [图片] / ![alt](url)
    t = re.sub(r"\[figure\][^\s\]\[]*", "", t, flags=re.I)
    t = re.sub(r"\[img\][^\s\]\[]*", "", t, flags=re.I)
    t = re.sub(r"\[(图片|图|figure|img)\]", "", t, flags=re.I)
    t = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", t)
    # markdown 强调与链接
    t = t.replace("**", "").replace("__", "").replace("~~", "")
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = t.replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit] + ("…" if len(t) > limit else "")


def _cn_to_en_type(zh: str) -> str | None:
    """中文题型 -> 英文存储值；已是英文直接返回。"""
    for en, label in QUESTION_TYPE_MAP.items():
        if label == zh or en == zh:
            return en
    return None


async def _used_question_ids(db, exclude_used: bool) -> set[str]:
    """选题池已有 + 已入练习的题目 id 集合。"""
    if not exclude_used:
        return set()
    used: set[str] = set()
    r = await db.execute(select(SelectionBasketItem.question_id))
    used.update(r.scalars().all())
    r = await db.execute(select(PracticeQuestion.source_question_id))
    used.update(r.scalars().all())
    return used


@router.post("/api/recommend", response_model=RecommendResponse)
async def recommend_questions(req: RecommendRequest, db=Depends(get_db)):
    # 1. 过滤候选
    query = (
        select(Question)
        .where(Question.is_deleted == False)  # noqa: E712
        .options(selectinload(Question.tags), selectinload(Question.source))
    )
    if req.subject:
        query = query.where(Question.subject == req.subject)
    if req.grade:
        query = query.where(Question.grade == req.grade)
    if req.question_types:
        en_types = [e for e in (_cn_to_en_type(t) for t in req.question_types) if e]
        if en_types:
            query = query.where(Question.question_type.in_(en_types))
    if req.tag_ids:
        query = query.where(Question.tags.any(Tag.id.in_(req.tag_ids)))
    if req.difficulty_bands:
        vals: list[int] = []
        for b in req.difficulty_bands:
            vals.extend(DIFFICULTY_BANDS.get(b, []))
        if vals:
            query = query.where(Question.difficulty.in_(vals))

    result = await db.execute(query)
    questions = result.scalars().all()

    # 2. 排除已用
    used = await _used_question_ids(db, req.exclude_used)
    candidates = [q for q in questions if q.id not in used]

    # 3. 打分
    tag_set = set(req.tag_ids)

    def score(q: Question) -> float:
        s = 0.0
        hit = len(tag_set & {t.id for t in q.tags}) if q.tags else 0
        s += hit * 3
        if req.question_types:
            en = _cn_to_en_type(q.question_type) if q.question_type else None
            if en and en in {_cn_to_en_type(t) for t in req.question_types if t}:
                s += 2
        if q.source and q.source.filename:
            s += 0.5
        if q.content:
            s += 0.5
        return s

    def reason(q: Question) -> str:
        parts: list[str] = []
        hit_tags = sorted((t.name for t in q.tags if t.id in tag_set), key=len)
        if hit_tags:
            joined = "、".join(hit_tags[:4])
            parts.append(f"命中{len(hit_tags)}个考点：{joined}")
        if q.difficulty:
            parts.append(f"难度：{DIFFICULTY_ZH.get(q.difficulty, q.difficulty)}")
        if q.source and q.source.filename:
            _fn = re.sub(r"\.(pdf|docx?|pptx?|txt)$", "", q.source.filename, flags=re.I)
            parts.append(f"来自《{_fn}》")
        return " · ".join(parts) or "符合筛选条件"

    scored = [(score(q), q) for q in candidates]
    random.shuffle(scored)
    scored.sort(key=lambda x: (-x[0], random.random()))

    # 4. 难度平均分配（选多档时每档均分）
    want = max(1, req.count) * 2
    picked: list[tuple[float, Question]] = []
    if req.difficulty_bands and len(req.difficulty_bands) > 1:
        bands = req.difficulty_bands
        per = -(-want // len(bands))  # ceil
        rest: list[tuple[float, Question]] = []
        for b in bands:
            vals = set(DIFFICULTY_BANDS.get(b, []))
            group = [x for x in scored if x[1].difficulty in vals]
            rest.extend(group[per:])
            picked.extend(group[:per])
        if len(picked) < want and rest:
            rest.sort(key=lambda x: (-x[0], random.random()))
            picked.extend(rest[: want - len(picked)])
        picked.sort(key=lambda x: (-x[0], random.random()))
        picked = picked[:want]
    else:
        picked = scored[:want]

    # 5. 组装
    items: list[RecommendItem] = []
    for _, q in picked:
        items.append(
            RecommendItem(
                id=q.id,
                question_type=q.question_type,
                subject=q.subject,
                difficulty=q.difficulty,
                grade=q.grade,
                content=_strip_markdown(q.content),
                tags=[t.name for t in (q.tags or [])],
                source_name=re.sub(r'\.(pdf|docx?|pptx?|txt)$', '', q.source.filename, flags=re.I) if q.source and q.source.filename else None,
                reason=reason(q),
            )
        )
    return RecommendResponse(items=items, total_candidates=len(candidates))
