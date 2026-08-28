# 练习制作系统 · 阶段一：选题池 + 练习创建 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现选题池（全局唯一、持久化）与练习创建的完整链路：题库选题 → 选题池 → 创建练习（按题型分组、题目快照、图片复制到练习目录）→ 练习列表管理。

**Architecture:** 后端新增 6 张表（selection_baskets / selection_basket_items / practices / practice_sections / practice_questions / practice_content_blocks），选题池与练习对题库零侵入（题目以快照复制，图片复制到 `data/practices/<id>/assets/` 并重写 `asset://` 引用）。前端在题库页加"加入选题池"入口，新增选题池页和练习列表页。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async（Mapped 风格）+ Alembic（SQLite batch）+ pytest（asyncio_mode=auto）+ Vue3 + Element Plus + axios。

**Spec:** `docs/superpowers/plans/2026-08-28-practice-builder-spec.md`（V1 已冻结；本计划实施阶段一，决策 8/9 约束阶段二、三）

## Global Constraints

- **题库零侵入**：不得修改 questions/tags/sources 现有接口行为；练习修改永不写回题库（决策 3）。
- 选题池全局只有一个（无账号系统，决策 1），刷新不丢数据（决策 7）。
- 快照必须复制图片资产，删除来源不影响练习。
- 本阶段不输出答案/解析（仅学生版，决策 2），但快照保留 answer/explanation 字段。
- 内容块表（practice_content_blocks）本阶段只建表不使用，阶段二编辑器消费。
- 后端命令（conda 环境 `question_platform`，工作目录 `backend/`）：
  - 测试：`conda run -n question_platform python -m pytest tests -q`
  - 迁移：`conda run -n question_platform python -m alembic revision --autogenerate -m "xxx"`，再 `python -m alembic upgrade head`
- 前端构建（工作目录 `frontend/`）：`$env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build`
- 每个任务结束必须通过对应测试并提交。

---

### Task 1: API 测试基建 + 选题池模型

**Files:**
- Modify: `backend/tests/conftest.py`
- Create: `backend/app/models/basket.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_models.py`
- Create: Alembic 迁移（autogenerate）

**Interfaces:**
- Produces: `SelectionBasket`（表 `selection_baskets`：id/created_at/updated_at）、`SelectionBasketItem`（表 `selection_basket_items`：id/basket_id/question_id/position/added_at，basket_id+question_id 唯一）；`client` / `test_db` pytest fixture 供后续 API 测试使用。

- [ ] **Step 1: 写 API 测试基建 conftest.py**

```python
"""Pytest configuration — shared API test fixtures."""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def test_db():
    """In-memory SQLite，全部建表，返回 session factory。"""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db, tmp_path, monkeypatch):
    """FastAPI 测试客户端：内存库 + 临时数据目录。"""
    async def override_get_db():
        async with test_db() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
```

- [ ] **Step 2: 写失败的模型测试**

在 `backend/tests/test_models.py` 顶部 import 中加入 `SelectionBasket, SelectionBasketItem`，文件末尾追加：

```python
# ── SelectionBasket ────────────────────────────────────

async def test_basket_item_unique(db: AsyncSession):
    basket = SelectionBasket()
    db.add(basket)
    await db.commit()

    item = SelectionBasketItem(basket_id=basket.id, question_id="q-1", position=0)
    db.add(item)
    await db.commit()
    assert item.id is not None

    dup = SelectionBasketItem(basket_id=basket.id, question_id="q-1", position=1)
    db.add(dup)
    with pytest.raises(Exception):
        await db.commit()
```

- [ ] **Step 3: 运行，确认失败**

Run: `conda run -n question_platform python -m pytest tests/test_models.py -q`
Expected: FAIL（ImportError: SelectionBasket 未定义）

- [ ] **Step 4: 实现 basket.py 模型**

```python
"""Selection basket models — temporary question basket for practice building."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SelectionBasket(Base):
    """V1 只有一个全局选题池（无账号），按需懒创建。"""

    __tablename__ = "selection_baskets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())


class SelectionBasketItem(Base):
    """选题池条目：只引用题库题目，不复制内容。"""

    __tablename__ = "selection_basket_items"
    __table_args__ = (UniqueConstraint("basket_id", "question_id", name="uq_basket_question"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    basket_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

在 `backend/app/models/__init__.py` 中加入 `from app.models.basket import SelectionBasket, SelectionBasketItem` 及 `__all__` 条目。

- [ ] **Step 5: 生成并执行迁移**

```
cd backend
conda run -n question_platform python -m alembic revision --autogenerate -m "selection basket tables"
conda run -n question_platform python -m alembic upgrade head
```

检查生成的迁移文件只包含 `selection_baskets`、`selection_basket_items` 两张表；若混入无关差异则手动清理该迁移文件后再 upgrade。

- [ ] **Step 6: 运行测试，确认通过**

Run: `conda run -n question_platform python -m pytest tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/models backend/tests backend/alembic/versions
git commit -m "feat: 选题池数据模型 + API 测试基建"
```

---

### Task 2: 选题池 API

**Files:**
- Create: `backend/app/routers/basket.py`
- Create: `backend/app/services/practice_service.py`（本任务只含基础函数）
- Modify: `backend/app/main.py`（注册 basket 路由）
- Test: `backend/tests/test_basket_api.py`

**Interfaces:**
- Consumes: Task 1 的模型与 `client` / `test_db` fixture。
- Produces:
  - `GET /api/basket` → `{basket_id, items: [{id, position, question: QuestionResponse}], total, type_stats: {中文题型: 数量}}`（跳过已软删题目）
  - `POST /api/basket/items` body `{question_ids}` → `{ok, added, total}`（去重、跳过已删）
  - `POST /api/basket/items/remove` body `{question_ids}` → `{ok, removed, total}`
  - `PUT /api/basket/reorder` body `{question_ids}` → `{ok}`
  - `DELETE /api/basket` → `{ok, removed}`
  - `practice_service.get_or_create_basket(db) -> SelectionBasket`、`practices_root()`、`practice_assets_dir(id)`、`resolve_practice_asset_urls(content, id)`、常量 `SECTION_TYPE_ORDER`、`ASSET_RE`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_basket_api.py`：

```python
"""API tests for selection basket."""

from app.models import Source, Question


async def seed_question(test_db, question_type="single_choice", content="测试题目", deleted=False):
    """造一道题，返回 question_id。"""
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf", ocr_status="done")
        db.add(source)
        await db.commit()
        q = Question(
            source_id=source.id, source_question_id="Q1", question_number=1,
            question_type=question_type, content=content, is_deleted=deleted,
        )
        db.add(q)
        await db.commit()
        await db.refresh(q)
        return q.id


async def test_basket_add_list_dedupe(client, test_db):
    q1 = await seed_question(test_db)
    q2 = await seed_question(test_db, question_type="fill_blank")

    res = await client.post("/api/basket/items", json={"question_ids": [q1, q2, q1]})
    assert res.status_code == 200
    assert res.json()["added"] == 2

    res = await client.get("/api/basket")
    data = res.json()
    assert data["total"] == 2
    assert data["type_stats"] == {"选择题": 1, "填空题": 1}
    assert [it["question"]["id"] for it in data["items"]] == [q1, q2]


async def test_basket_skip_deleted(client, test_db):
    qd = await seed_question(test_db, deleted=True)
    res = await client.post("/api/basket/items", json={"question_ids": [qd]})
    assert res.json()["added"] == 0


async def test_basket_remove_and_clear(client, test_db):
    q1 = await seed_question(test_db)
    q2 = await seed_question(test_db)
    await client.post("/api/basket/items", json={"question_ids": [q1, q2]})

    res = await client.post("/api/basket/items/remove", json={"question_ids": [q1]})
    assert res.json()["removed"] == 1

    res = await client.delete("/api/basket")
    assert res.json()["removed"] == 1
    assert (await client.get("/api/basket")).json()["total"] == 0


async def test_basket_reorder(client, test_db):
    q1 = await seed_question(test_db)
    q2 = await seed_question(test_db)
    await client.post("/api/basket/items", json={"question_ids": [q1, q2]})

    await client.put("/api/basket/reorder", json={"question_ids": [q2, q1]})
    res = await client.get("/api/basket")
    assert [it["question"]["id"] for it in res.json()["items"]] == [q2, q1]
```

- [ ] **Step 2: 运行，确认失败**

Run: `conda run -n question_platform python -m pytest tests/test_basket_api.py -q`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 实现 practice_service.py（基础部分）**

```python
"""Practice service — basket helpers, snapshot creation, asset copying."""

import re
import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.basket import SelectionBasket

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
```

- [ ] **Step 4: 实现 basket.py 路由**

```python
"""Selection basket router — global single basket, add/remove/reorder/clear."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Question
from app.models.basket import SelectionBasketItem
from app.schemas.question import QuestionResponse
from app.services import practice_service
from app.utils.question_types import map_question_type

router = APIRouter()


class QuestionIdsRequest(BaseModel):
    question_ids: list[str]


async def _basket_total(db: AsyncSession, basket_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(SelectionBasketItem)
        .where(SelectionBasketItem.basket_id == basket_id)
    )
    return result.scalar() or 0


@router.get("/api/basket")
async def get_basket(db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        select(SelectionBasketItem)
        .where(SelectionBasketItem.basket_id == basket.id)
        .order_by(SelectionBasketItem.position)
    )
    items = result.scalars().all()

    qids = [it.question_id for it in items]
    questions_map = {}
    if qids:
        qr = await db.execute(
            select(Question).where(Question.id.in_(qids)).options(selectinload(Question.tags))
        )
        questions_map = {q.id: q for q in qr.scalars().all()}

    payload_items, type_stats = [], {}
    for it in items:
        q = questions_map.get(it.question_id)
        if not q or q.is_deleted:
            continue
        payload_items.append({
            "id": it.id,
            "position": it.position,
            "question": QuestionResponse.model_validate(q),
        })
        zh = map_question_type(q.question_type)
        type_stats[zh] = type_stats.get(zh, 0) + 1

    return {"basket_id": basket.id, "items": payload_items, "total": len(payload_items), "type_stats": type_stats}


@router.post("/api/basket/items")
async def add_items(req: QuestionIdsRequest, db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        select(SelectionBasketItem).where(SelectionBasketItem.basket_id == basket.id)
    )
    existing = {it.question_id for it in result.scalars().all()}
    result = await db.execute(
        select(func.max(SelectionBasketItem.position)).where(SelectionBasketItem.basket_id == basket.id)
    )
    pos = (result.scalar() or -1) + 1

    added = 0
    for qid in req.question_ids:
        if qid in existing:
            continue
        q = await db.get(Question, qid)
        if not q or q.is_deleted:
            continue
        db.add(SelectionBasketItem(basket_id=basket.id, question_id=qid, position=pos))
        existing.add(qid)
        pos += 1
        added += 1
    await db.commit()
    return {"ok": True, "added": added, "total": await _basket_total(db, basket.id)}


@router.post("/api/basket/items/remove")
async def remove_items(req: QuestionIdsRequest, db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        delete(SelectionBasketItem).where(
            SelectionBasketItem.basket_id == basket.id,
            SelectionBasketItem.question_id.in_(req.question_ids),
        )
    )
    await db.commit()
    return {"ok": True, "removed": result.rowcount, "total": await _basket_total(db, basket.id)}


@router.put("/api/basket/reorder")
async def reorder_items(req: QuestionIdsRequest, db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        select(SelectionBasketItem).where(SelectionBasketItem.basket_id == basket.id)
    )
    items = {it.question_id: it for it in result.scalars().all()}
    for pos, qid in enumerate(req.question_ids):
        if qid in items:
            items[qid].position = pos
    await db.commit()
    return {"ok": True}


@router.delete("/api/basket")
async def clear_basket(db: AsyncSession = Depends(get_db)):
    basket = await practice_service.get_or_create_basket(db)
    result = await db.execute(
        delete(SelectionBasketItem).where(SelectionBasketItem.basket_id == basket.id)
    )
    await db.commit()
    return {"ok": True, "removed": result.rowcount}
```

- [ ] **Step 5: main.py 注册路由**

```python
from app.routers import upload, questions, tags, settings as settings_router, basket
...
app.include_router(basket.router)
```

（practices 路由在 Task 5 注册。）

- [ ] **Step 6: 运行测试，确认通过**

Run: `conda run -n question_platform python -m pytest tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/basket.py backend/app/services/practice_service.py backend/app/main.py backend/tests/test_basket_api.py
git commit -m "feat: 选题池 API（加入/移除/重排/清空/统计）"
```

---

### Task 3: 练习数据模型

**Files:**
- Create: `backend/app/models/practice.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/tests/test_models.py`
- Create: Alembic 迁移（autogenerate）

**Interfaces:**
- Produces: `Practice`（id/title/subtitle/subject/grade/status/page_config JSON/时间戳，sections 关系）、`PracticeSection`（title/section_type/position/show_title/start_on_new_page，questions 关系）、`PracticeQuestion`（source_question_id 无外键、position、question_number、question_type、subject、difficulty、score、content_snapshot/options_snapshot/answer_snapshot/explanation_snapshot、source_version、is_modified、layout_config JSON，blocks 关系）、`PracticeContentBlock`（block_type/position/content/style_config/source_asset_id）。级联删除：Practice → sections → questions → blocks。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_models.py` 顶部 import 加入 `Practice, PracticeSection, PracticeQuestion, PracticeContentBlock`，末尾追加：

```python
# ── Practice cascade ───────────────────────────────────

async def test_practice_cascade_delete(db: AsyncSession):
    practice = Practice(title="浮力练习", subject="物理")
    db.add(practice)
    await db.flush()

    section = PracticeSection(practice_id=practice.id, title="选择题", section_type="选择题", position=0)
    db.add(section)
    await db.flush()

    pq = PracticeQuestion(
        practice_id=practice.id, section_id=section.id,
        source_question_id="q-xyz", position=0,
        question_type="single_choice", content_snapshot="题干 ![图](asset://practice/ab.webp)",
        options_snapshot=[{"label": "A", "content": "1"}],
    )
    db.add(pq)
    await db.flush()

    block = PracticeContentBlock(practice_question_id=pq.id, block_type="text", position=0, content="题干")
    db.add(block)
    await db.commit()

    await db.delete(practice)
    await db.commit()

    for model in (PracticeSection, PracticeQuestion, PracticeContentBlock):
        result = await db.execute(select(model))
        assert result.scalars().first() is None
```

（`select` 已在该文件顶部从 sqlalchemy 导入；若没有则补充。）

- [ ] **Step 2: 运行，确认失败**

Run: `conda run -n question_platform python -m pytest tests/test_models.py -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 practice.py 模型**

```python
"""Practice models — practice, sections, question snapshots, content blocks."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Practice(Base):
    __tablename__ = "practices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / exported
    page_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    sections = relationship(
        "PracticeSection", back_populates="practice",
        cascade="all, delete-orphan", order_by="PracticeSection.position",
    )


class PracticeSection(Base):
    __tablename__ = "practice_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    practice_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    section_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 题型中文名或 "custom"
    position: Mapped[int] = mapped_column(Integer, default=0)
    show_title: Mapped[bool] = mapped_column(Boolean, default=True)
    start_on_new_page: Mapped[bool] = mapped_column(Boolean, default=False)

    practice = relationship("Practice", back_populates="sections")
    questions = relationship(
        "PracticeQuestion", back_populates="section",
        cascade="all, delete-orphan", order_by="PracticeQuestion.position",
    )


class PracticeQuestion(Base):
    """题目快照：加入练习时复制，编辑永不写回题库。"""

    __tablename__ = "practice_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    practice_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # 不设外键：快照独立于题库，原题删除不影响练习
    source_question_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    question_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    question_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(50), nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_version: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    layout_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    section = relationship("PracticeSection", back_populates="questions")
    blocks = relationship(
        "PracticeContentBlock", back_populates="question",
        cascade="all, delete-orphan", order_by="PracticeContentBlock.position",
    )


class PracticeContentBlock(Base):
    """题内内容块（阶段二编辑器消费，阶段一仅建表）。"""

    __tablename__ = "practice_content_blocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    practice_question_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False)  # text/image/options/answer_space/answer/explanation
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_asset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    question = relationship("PracticeQuestion", back_populates="blocks")
```

- [ ] **Step 4: 生成并执行迁移**

```
cd backend
conda run -n question_platform python -m alembic revision --autogenerate -m "practice tables"
conda run -n question_platform python -m alembic upgrade head
```

检查迁移文件只含 4 张新表（practices / practice_sections / practice_questions / practice_content_blocks）。

- [ ] **Step 5: 运行测试，确认通过**

Run: `conda run -n question_platform python -m pytest tests -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models backend/tests/test_models.py backend/alembic/versions
git commit -m "feat: 练习数据模型（练习/小节/题目快照/内容块）"
```

---

### Task 4: 快照服务（含图片资产复制）

**Files:**
- Modify: `backend/app/services/practice_service.py`
- Test: `backend/tests/test_snapshot.py`

**Interfaces:**
- Consumes: Task 3 模型；`Source.ocr_result_path` 目录（含 `figures/xxx.webp`，兼容旧双写 `figures/figures/`）。
- Produces:
  - `create_practice_from_questions(db, title, subtitle, subject, grade, questions) -> Practice`：按题型中文分组建小节（顺序 `SECTION_TYPE_ORDER`），逐题快照。
  - `snapshot_question(db, practice, section, question, position) -> PracticeQuestion`
  - `_copy_referenced_assets(content, ocr_dir, assets_dir) -> str | None`（模块内函数，单测直接覆盖）
  - 图片复制命名：`<8位随机hex>_<原文件名>`，引用改写为 `asset://practice/<name>`；文件缺失时保留原引用。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_snapshot.py`：

```python
"""Snapshot service tests — asset copy + practice creation."""

from app.models import Source, Question
from app.services import practice_service


async def _make_source_with_figure(test_db, tmp_path):
    """造一个带 figures/test_fig.webp 的来源，返回题目对象。"""
    ocr_dir = tmp_path / "ocr" / "doc1"
    (ocr_dir / "figures").mkdir(parents=True)
    (ocr_dir / "figures" / "test_fig.webp").write_bytes(b"fake-webp")

    async with test_db() as db:
        source = Source(
            filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
            ocr_status="done", ocr_result_path=str(ocr_dir),
        )
        db.add(source)
        await db.commit()
        q = Question(
            source_id=source.id, source_question_id="Q1", question_number=1,
            question_type="single_choice", subject="physics", difficulty=3,
            content="第一行 ![图](asset://figures/test_fig.webp) 第二行",
            options=[{"label": "A", "content": "x"}], answer="A",
        )
        db.add(q)
        await db.commit()
        await db.refresh(q)
        return q


def test_copy_referenced_assets(tmp_path):
    ocr_dir = tmp_path / "ocr"
    (ocr_dir / "figures").mkdir(parents=True)
    (ocr_dir / "figures" / "a.webp").write_bytes(b"img")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()

    content = "看 ![图](asset://figures/a.webp) 再看 ![图](asset://figures/figures/a.webp)"
    new_content = practice_service._copy_referenced_assets(content, ocr_dir, assets_dir)

    assert "asset://practice/" in new_content
    assert "asset://figures/" not in new_content
    assert len(list(assets_dir.glob("*_a.webp"))) == 2


def test_copy_missing_file_keeps_reference(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    content = "![图](asset://figures/nope.webp)"
    assert practice_service._copy_referenced_assets(content, tmp_path, assets_dir) == content


async def test_create_practice_groups_by_type(test_db, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    q_choice = await _make_source_with_figure(test_db, tmp_path)
    async with test_db() as db:
        q_fill = Question(
            source_id=q_choice.source_id, source_question_id="Q2", question_number=2,
            question_type="fill_blank", content="填空 ![图](asset://figures/test_fig.webp)",
        )
        db.add(q_fill)
        await db.commit()
        await db.refresh(q_fill)

        practice = await practice_service.create_practice_from_questions(
            db, title="测试练习", subtitle=None, subject="physics", grade="初三",
            questions=[q_fill, q_choice],  # 故意乱序，验证按题型分组排序
        )

        assert practice.status == "draft"
        assert [s.title for s in practice.sections] == ["选择题", "填空题"]
        choice_pq = practice.sections[0].questions[0]
        assert choice_pq.answer_snapshot == "A"
        assert choice_pq.is_modified is False
        assert "asset://practice/" in choice_pq.content_snapshot
        assets = list(practice_service.practice_assets_dir(practice.id).glob("*.webp"))
        assert len(assets) == 2
```

- [ ] **Step 2: 运行，确认失败**

Run: `conda run -n question_platform python -m pytest tests/test_snapshot.py -q`
Expected: FAIL（`_copy_referenced_assets` / `create_practice_from_questions` 不存在）

- [ ] **Step 3: 在 practice_service.py 追加实现**

顶部补充 import：`from app.models import Question, Source`（`snapshot_question` 的类型标注需要 `Question`）、`from app.models.practice import Practice, PracticeSection, PracticeQuestion`、`from app.utils.question_types import map_question_type`（`re/shutil/uuid/Path/select/AsyncSession/settings` 已有）。追加：

```python
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
    await db.refresh(practice)
    return practice
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `conda run -n question_platform python -m pytest tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/practice_service.py backend/tests/test_snapshot.py
git commit -m "feat: 练习快照服务（按题型分组 + 图片资产复制）"
```

---

### Task 5: 练习 API（创建 / 列表 / 详情 / 改名 / 删除 / 资产访问）

**Files:**
- Create: `backend/app/schemas/practice.py`
- Create: `backend/app/routers/practices.py`
- Modify: `backend/app/main.py`（注册 practices 路由）
- Test: `backend/tests/test_practice_api.py`

**Interfaces:**
- Consumes: Task 2 basket API、Task 4 `create_practice_from_questions` / `resolve_practice_asset_urls` / `practices_root` / `practice_assets_dir`。
- Produces:
  - `POST /api/practices` body `{title, subtitle?, subject?, grade?, from_basket=true, question_ids?, clear_basket=false}` → `PracticeResponse`；`from_basket=false` 时用 `question_ids`；无可用题目返回 400。
  - `GET /api/practices` → `{practices: [PracticeBrief], total}`（含 question_count，按 created_at 倒序）
  - `GET /api/practices/{id}` → 含 `sections[].questions[]`，content 已解析为 `/api/practices/{id}/assets/...` HTTP URL
  - `PUT /api/practices/{id}` body `{title?, subtitle?, subject?, grade?}`
  - `DELETE /api/practices/{id}` → 删记录 + `rmtree` 练习目录
  - `GET /api/practices/{id}/assets/{path}` → FileResponse（防目录穿越）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_practice_api.py`：

```python
"""API tests for practices."""

from app.models import Source, Question


async def seed_basket_question(test_db, tmp_path, question_type="single_choice"):
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True, exist_ok=True)
    (ocr_dir / "figures" / "f.webp").write_bytes(b"img")
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                     question_type=question_type, content="题 ![图](asset://figures/f.webp)")
        db.add(q)
        await db.commit()
        await db.refresh(q)
        return q.id


async def test_create_from_basket(client, test_db, tmp_path):
    q1 = await seed_basket_question(test_db, tmp_path)
    q2 = await seed_basket_question(test_db, tmp_path, question_type="fill_blank")
    await client.post("/api/basket/items", json={"question_ids": [q1, q2]})

    res = await client.post("/api/practices", json={
        "title": "浮力练习", "subject": "physics", "grade": "初三",
        "from_basket": True, "clear_basket": True,
    })
    assert res.status_code == 200
    practice = res.json()
    assert practice["question_count"] == 2
    assert [s["title"] for s in practice["sections"]] == ["选择题", "填空题"]
    # 快照内容已解析为 HTTP 资产 URL
    content = practice["sections"][0]["questions"][0]["content"]
    assert f"/api/practices/{practice['id']}/assets/" in content

    # 选题池已清空（决策 7）
    assert (await client.get("/api/basket")).json()["total"] == 0

    # 资产文件可访问，且路径穿越被拒（403 或 404 均可，取决于路径解码方式）
    asset_url = content[content.index("/api/practices"):].split(")")[0]
    assert (await client.get(asset_url)).content == b"img"
    bad = asset_url.rsplit("/", 1)[0] + "/..%2F..%2Fdb.sqlite3"
    res_bad = await client.get(bad)
    assert res_bad.status_code in (403, 404)
    assert res_bad.content != (await client.get(asset_url)).content


async def test_create_empty_basket_fails(client, test_db, tmp_path):
    res = await client.post("/api/practices", json={"title": "空练习"})
    assert res.status_code == 400


async def test_create_from_explicit_ids(client, test_db, tmp_path):
    q1 = await seed_basket_question(test_db, tmp_path)
    res = await client.post("/api/practices", json={
        "title": "指定题目", "from_basket": False, "question_ids": [q1],
    })
    assert res.status_code == 200
    assert res.json()["question_count"] == 1


async def test_list_update_delete(client, test_db, tmp_path):
    q1 = await seed_basket_question(test_db, tmp_path)
    await client.post("/api/basket/items", json={"question_ids": [q1]})
    res = await client.post("/api/practices", json={"title": "练习A"})
    pid = res.json()["id"]

    res = await client.get("/api/practices")
    assert res.json()["total"] == 1
    assert res.json()["practices"][0]["question_count"] == 1

    res = await client.put(f"/api/practices/{pid}", json={"title": "练习B"})
    assert res.json()["title"] == "练习B"

    res = await client.delete(f"/api/practices/{pid}")
    assert res.json()["ok"] is True
    assert not (tmp_path / "practices" / pid).exists()
    assert (await client.get("/api/practices")).json()["total"] == 0
```

- [ ] **Step 2: 运行，确认失败**

Run: `conda run -n question_platform python -m pytest tests/test_practice_api.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 实现 schemas/practice.py**

```python
"""Pydantic schemas for Practice."""

from datetime import datetime
from pydantic import BaseModel


class PracticeCreateRequest(BaseModel):
    title: str
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    from_basket: bool = True
    question_ids: list[str] | None = None
    clear_basket: bool = False


class PracticeUpdateRequest(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None


class PracticeBrief(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    status: str
    question_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None


class PracticeQuestionOut(BaseModel):
    id: str
    position: int
    source_question_id: str | None = None
    question_number: int | None = None
    question_type: str | None = None
    difficulty: int | None = None
    score: float | None = None
    content: str | None = None
    options: list | None = None
    is_modified: bool


class PracticeSectionOut(BaseModel):
    id: str
    title: str
    section_type: str
    position: int
    show_title: bool
    start_on_new_page: bool
    questions: list[PracticeQuestionOut]


class PracticeResponse(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    subject: str | None = None
    grade: str | None = None
    status: str
    question_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None
    sections: list[PracticeSectionOut]


class PracticeListResponse(BaseModel):
    practices: list[PracticeBrief]
    total: int
```

- [ ] **Step 4: 实现 routers/practices.py**

```python
"""Practice router — create from basket, list, detail, update, delete, assets."""

import shutil

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Question
from app.models.basket import SelectionBasketItem
from app.models.practice import Practice, PracticeQuestion, PracticeSection
from app.schemas.practice import (
    PracticeBrief, PracticeCreateRequest, PracticeListResponse,
    PracticeQuestionOut, PracticeResponse, PracticeSectionOut, PracticeUpdateRequest,
)
from app.services import practice_service

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
        .options(selectinload(Practice.sections).selectinload(PracticeSection.questions))
    )
    return result.scalar_one_or_none()


def _practice_response(practice: Practice) -> PracticeResponse:
    sections, total = [], 0
    for s in practice.sections:
        questions = [
            PracticeQuestionOut(
                id=pq.id, position=pq.position, source_question_id=pq.source_question_id,
                question_number=pq.question_number, question_type=pq.question_type,
                difficulty=pq.difficulty, score=pq.score,
                content=practice_service.resolve_practice_asset_urls(pq.content_snapshot, practice.id),
                options=pq.options_snapshot, is_modified=pq.is_modified,
            )
            for pq in s.questions
        ]
        total += len(questions)
        sections.append(PracticeSectionOut(
            id=s.id, title=s.title, section_type=s.section_type, position=s.position,
            show_title=s.show_title, start_on_new_page=s.start_on_new_page, questions=questions,
        ))
    return PracticeResponse(
        id=practice.id, title=practice.title, subtitle=practice.subtitle,
        subject=practice.subject, grade=practice.grade, status=practice.status,
        question_count=total, created_at=practice.created_at, updated_at=practice.updated_at,
        sections=sections,
    )


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
            status=p.status, question_count=cnt.scalar() or 0,
            created_at=p.created_at, updated_at=p.updated_at,
        ))
    return PracticeListResponse(practices=briefs, total=len(briefs))


@router.get("/api/practices/{practice_id}", response_model=PracticeResponse)
async def get_practice(practice_id: str, db: AsyncSession = Depends(get_db)):
    practice = await _get_practice_full(db, practice_id)
    if not practice:
        raise HTTPException(404, "Practice not found")
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
```

- [ ] **Step 5: main.py 注册路由**

import 与 include 加入 `practices`（与 basket 并列）。

- [ ] **Step 6: 运行测试，确认通过**

Run: `conda run -n question_platform python -m pytest tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/practices.py backend/app/schemas/practice.py backend/app/main.py backend/tests/test_practice_api.py
git commit -m "feat: 练习 API（从选题池创建/列表/详情/改名/删除/资产访问）"
```

---

### Task 6: 题库筛选新增“有答案 / 有解析”

**Files:**
- Modify: `backend/app/routers/questions.py`（list_questions）
- Test: `backend/tests/test_question_filters.py`

**Interfaces:**
- Produces: `GET /api/questions?has_answer=true|false&has_explanation=true|false`；不传则不过滤；空字符串视为无。
- 约束：仅新增查询参数，不改变现有任何筛选行为（零侵入）。

- [ ] **Step 1: 写失败测试**

```python
"""API tests for has_answer / has_explanation filters."""

from app.models import Source, Question


async def seed(test_db, **fields):
    async with test_db() as db:
        source = Source(filename="f.pdf", file_path="/tmp/f.pdf", file_type="pdf")
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q", question_number=1,
                     content="c", **fields)
        db.add(q)
        await db.commit()
        await db.refresh(q)
        return q.id


async def test_has_answer_filter(client, test_db):
    await seed(test_db, answer="A")
    await seed(test_db, answer="")
    await seed(test_db)  # None

    assert (await client.get("/api/questions", params={"has_answer": "true"})).json()["total"] == 1
    assert (await client.get("/api/questions", params={"has_answer": "false"})).json()["total"] == 2


async def test_has_explanation_filter(client, test_db):
    await seed(test_db, explanation="因为所以")
    await seed(test_db)

    assert (await client.get("/api/questions", params={"has_explanation": "true"})).json()["total"] == 1
```

- [ ] **Step 2: 运行，确认失败**

Run: `conda run -n question_platform python -m pytest tests/test_question_filters.py -q`
Expected: FAIL（参数被忽略，total 不符）

- [ ] **Step 3: 实现过滤**

`list_questions` 签名追加两个参数：

```python
    has_answer: bool | None = Query(default=None, description="true=仅有答案，false=仅无答案"),
    has_explanation: bool | None = Query(default=None),
```

在现有 `if grade:` 分支之后追加：

```python
    if has_answer is not None:
        cond = Question.answer.isnot(None) & (func.trim(Question.answer) != "")
        query = query.where(cond if has_answer else ~cond)
    if has_explanation is not None:
        cond = Question.explanation.isnot(None) & (func.trim(Question.explanation) != "")
        query = query.where(cond if has_explanation else ~cond)
```

- [ ] **Step 4: 运行全部测试，确认通过**

Run: `conda run -n question_platform python -m pytest tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/questions.py backend/tests/test_question_filters.py
git commit -m "feat: 题库筛选支持有答案/有解析"
```

---

### Task 7: 前端 · 题库页加入选题池入口

**Files:**
- Modify: `frontend/src/views/LibraryView.vue`

**Interfaces:**
- Consumes: Task 2 `POST /api/basket/items`、`GET /api/basket`。
- Produces: 批量操作栏“加入选题池”按钮；页头右侧“选题池 (N)”入口跳转 `/basket`；现有批量打标/修正/详情抽屉零改动。

- [ ] **Step 1: 批量栏加按钮**

批量操作栏中 `AI 批量打标` 与 `批量删除` 之间插入：

```html
      <el-button type="primary" size="small" @click="addToBasket">加入选题池</el-button>
```

- [ ] **Step 2: 页头加选题池入口**

```html
    <div class="library-header">
      <div>
        <h2>题库管理</h2>
        <p class="subtitle">浏览、搜索、筛选、批量操作所有题目</p>
      </div>
      <el-button @click="$router.push('/basket')">
        <el-icon><ShoppingCart /></el-icon> 选题池 ({{ basketTotal }})
      </el-button>
    </div>
```

若 `.library-header` 样式无 `display: flex; justify-content: space-between; align-items: flex-start;` 则补上。

- [ ] **Step 3: script 逻辑**

```js
const basketTotal = ref(0)

const loadBasketTotal = async () => {
  try {
    const res = await axios.get('/api/basket')
    basketTotal.value = res.data.total
  } catch (e) { /* 静默 */ }
}

const addToBasket = async () => {
  try {
    const res = await axios.post('/api/basket/items', { question_ids: [...selectedIds] })
    if (res.data.added === 0) {
      ElMessage.warning('所选题目均已在选题池中')
    } else {
      ElMessage.success(`已加入选题池 ${res.data.added} 题（池中共 ${res.data.total} 题）`)
    }
    basketTotal.value = res.data.total
  } catch (e) {
    ElMessage.error('加入选题池失败')
  }
}
```

在页面初始化处（现有 `onMounted` 或首次 `loadQuestions` 同位置）追加 `loadBasketTotal()`。

- [ ] **Step 4: 构建验证**

```
cd frontend
$env:PATH = "C:\Users\Administrator\.conda\envs\question_platform;" + $env:PATH ; node node_modules/vite/bin/vite.js build
```

Expected: 构建成功。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/LibraryView.vue
git commit -m "feat: 题库页加入选题池入口"
```

---

### Task 8: 前端 · 选题池页 + 导航路由 + 题型映射工具 + BasketView

**Files:**
- Create: `frontend/src/utils/questionTypes.js`
- Create: `frontend/src/views/BasketView.vue`
- Modify: `frontend/src/router/index.js`、`frontend/src/App.vue`

**Interfaces:**
- Consumes: Task 2 全部 basket API、Task 5 `POST /api/practices`；`utils/render.js` 的 `renderPreview(text, maxLen)`。
- Produces: `/basket` 页面：题目列表（内容预览/题型/难度）、题型统计与二次筛选、移除、上移/下移、清空（确认）、“创建练习”对话框（标题必填 + 清空选题池勾选，决策 7）→ 成功后跳 `/practices`。

- [ ] **Step 1: 题型映射工具**

`frontend/src/utils/questionTypes.js`：

```js
// 与后端 app/utils/question_types.py 的 QUESTION_TYPE_MAP 保持一致
export const QUESTION_TYPE_MAP = {
  single_choice: '选择题',
  multiple_choice: '多选题',
  fill_blank: '填空题',
  comprehensive: '综合题',
  experiment: '实验题',
  calculation: '计算题',
  short_answer: '简答题',
  essay: '论述题',
  unknown: '未知题型',
}
```

- [ ] **Step 2: 路由与导航**

`router/index.js` 在 `/library` 之后追加：

```js
  {
    path: '/basket',
    name: 'Basket',
    component: () => import('../views/BasketView.vue'),
  },
```

`App.vue` 侧边栏“题库管理”与“AI 助手”之间插入：

```html
        <el-menu-item index="/basket">
          <el-icon><ShoppingCart /></el-icon>
          <span>选题池</span>
        </el-menu-item>
```

- [ ] **Step 3: BasketView.vue**

```vue
<template>
  <div class="basket-view">
    <div class="basket-header">
      <div>
        <h2>临时选题池</h2>
        <p class="subtitle">本次练习的候选题目，刷新不丢失</p>
      </div>
      <div>
        <el-button @click="$router.push('/library')">继续选题</el-button>
        <el-button danger plain :disabled="!items.length" @click="clearBasket">清空</el-button>
        <el-button type="primary" :disabled="!items.length" @click="showCreate = true">创建练习</el-button>
      </div>
    </div>

    <el-card v-if="items.length" style="margin-bottom: 12px;">
      <el-tag v-for="(n, t) in basket.type_stats" :key="t" style="margin-right: 8px;">{{ t }} × {{ n }}</el-tag>
      <el-select v-model="typeFilter" placeholder="按题型筛选" clearable style="width: 140px; margin-left: 16px;">
        <el-option v-for="t in Object.keys(basket.type_stats || {})" :key="t" :label="t" :value="t" />
      </el-select>
    </el-card>

    <el-card>
      <el-empty v-if="!items.length" description="选题池为空，去题库选题吧">
        <el-button type="primary" @click="$router.push('/library')">去题库</el-button>
      </el-empty>
      <div v-for="(it, idx) in filteredItems" :key="it.question.id" class="basket-item">
        <div class="item-main">
          <div class="item-meta">
            <el-tag size="small">{{ typeZh(it.question.question_type) }}</el-tag>
            <el-tag v-if="it.question.difficulty" size="small" type="warning">{{ it.question.difficulty }} 星</el-tag>
          </div>
          <div class="item-content" v-html="renderPreview(it.question.content)"></div>
        </div>
        <div class="item-actions">
          <el-button size="small" text :disabled="idx === 0" @click="move(idx, -1)"><el-icon><Top /></el-icon></el-button>
          <el-button size="small" text :disabled="idx === filteredItems.length - 1" @click="move(idx, 1)"><el-icon><Bottom /></el-icon></el-button>
          <el-button size="small" text type="danger" @click="remove(it)"><el-icon><Delete /></el-icon></el-button>
        </div>
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="创建练习" width="420px">
      <el-form label-width="90px">
        <el-form-item label="练习标题" required>
          <el-input v-model="createForm.title" placeholder="如：浮力专项练习" />
        </el-form-item>
        <el-form-item label="学科">
          <el-input v-model="createForm.subject" placeholder="如：物理（可留空）" />
        </el-form-item>
        <el-form-item label="年级">
          <el-select v-model="createForm.grade" clearable style="width: 100%;">
            <el-option v-for="g in ['初一', '初二', '初三', '中考']" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="创建后">
          <el-checkbox v-model="createForm.clear_basket">清空选题池</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createPractice">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { renderPreview } from '../utils/render'
import { QUESTION_TYPE_MAP } from '../utils/questionTypes'

const router = useRouter()
const basket = ref({ items: [], type_stats: {} })
const typeFilter = ref('')
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ title: '', subject: '', grade: '', clear_basket: true })

const items = computed(() => basket.value.items || [])
const filteredItems = computed(() =>
  typeFilter.value
    ? items.value.filter(it => typeZh(it.question.question_type) === typeFilter.value)
    : items.value
)

const typeZh = (t) => QUESTION_TYPE_MAP[t] || t || '未知题型'

const load = async () => {
  const res = await axios.get('/api/basket')
  basket.value = res.data
}

const remove = async (it) => {
  await axios.post('/api/basket/items/remove', { question_ids: [it.question.id] })
  await load()
}

const move = async (idx, dir) => {
  // 筛选子序列内移动，再按原位置回填全量顺序
  const ids = filteredItems.value.map(it => it.question.id)
  const [x] = ids.splice(idx, 1)
  ids.splice(idx + dir, 0, x)
  const visible = new Set(filteredItems.value.map(it => it.question.id))
  let vi = 0
  const merged = items.value.map(it => visible.has(it.question.id) ? ids[vi++] : it.question.id)
  await axios.put('/api/basket/reorder', { question_ids: merged })
  await load()
}

const clearBasket = async () => {
  await ElMessageBox.confirm('确定清空选题池？', '提示', { type: 'warning' })
  await axios.delete('/api/basket')
  ElMessage.success('选题池已清空')
  await load()
}

const createPractice = async () => {
  if (!createForm.value.title.trim()) {
    ElMessage.warning('请输入练习标题')
    return
  }
  creating.value = true
  try {
    await axios.post('/api/practices', {
      title: createForm.value.title.trim(),
      subject: createForm.value.subject || null,
      grade: createForm.value.grade || null,
      from_basket: true,
      clear_basket: createForm.value.clear_basket,
    })
    ElMessage.success('练习已创建')
    router.push('/practices')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.basket-view { max-width: 1000px; margin: 0 auto; }
.basket-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.subtitle { color: #909399; }
.basket-item { display: flex; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid #ebeef5; }
.item-main { flex: 1; min-width: 0; }
.item-meta { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.item-content { color: #303133; font-size: 14px; }
.item-content :deep(img) { max-height: 80px; }
.item-actions { display: flex; flex-direction: column; }
</style>
```

- [ ] **Step 4: 构建验证**（同 Task 7 Step 4）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/BasketView.vue frontend/src/utils/questionTypes.js frontend/src/router/index.js frontend/src/App.vue
git commit -m "feat: 选题池页面（筛选/排序/移除/创建练习）"
```

---

### Task 9: 前端 · 练习列表页 + 导航路由 + PracticeListView（列表/改名/删除/只读详情）

**Files:**
- Create: `frontend/src/views/PracticeListView.vue`
- Modify: `frontend/src/router/index.js`、`frontend/src/App.vue`

**Interfaces:**
- Consumes: Task 5 `GET/PUT/DELETE /api/practices`、`GET /api/practices/{id}`；`utils/render.js` 的 `renderPreview`。
- Produces: `/practices` 页面：练习卡片（标题/学科/年级/题数/状态/时间）、重命名对话框、删除确认、点击卡片弹只读详情（按小节展示快照内容；编辑器入口在阶段二提供）。另在 `router/index.js` 与 `App.vue` 侧边栏（“选题池”之后）加 `/practices` 路由与菜单项（图标 `<Notebook />`，文案“练习”）。
- 注：年级为空时不显示；`status === 'exported'` 显示“已导出”标签，否则“草稿”。

- [ ] **Step 1: PracticeListView.vue**

```vue
<template>
  <div class="practice-list-view">
    <div class="page-header">
      <div>
        <h2>练习列表</h2>
        <p class="subtitle">从选题池创建练习，编辑器即将开放</p>
      </div>
      <el-button @click="$router.push('/basket')"><el-icon><ShoppingCart /></el-icon> 去选题池创建</el-button>
    </div>

    <el-empty v-if="!practices.length" description="还没有练习，从选题池创建一份吧" />
    <div class="practice-grid" v-else>
      <el-card v-for="p in practices" :key="p.id" class="practice-card" shadow="hover" @click="openDetail(p)">
        <div class="card-title">
          <span>{{ p.title }}</span>
          <el-tag size="small" :type="p.status === 'exported' ? 'success' : 'info'">{{ p.status === 'exported' ? '已导出' : '草稿' }}</el-tag>
        </div>
        <div class="card-meta">
          <span v-if="p.subject">{{ p.subject }}</span>
          <span v-if="p.grade">{{ p.grade }}</span>
          <span>{{ p.question_count }} 题</span>
        </div>
        <div class="card-footer">
          <span class="card-time">{{ formatTime(p.updated_at || p.created_at) }}</span>
          <span>
            <el-button size="small" text @click.stop="rename(p)">重命名</el-button>
            <el-button size="small" text type="danger" @click.stop="remove(p)">删除</el-button>
          </span>
        </div>
      </el-card>
    </div>

    <!-- 重命名 -->
    <el-dialog v-model="showRename" title="重命名练习" width="380px">
      <el-input v-model="renameTitle" />
      <template #footer>
        <el-button @click="showRename = false">取消</el-button>
        <el-button type="primary" @click="doRename">保存</el-button>
      </template>
    </el-dialog>

    <!-- 只读详情 -->
    <el-dialog v-model="showDetail" :title="detail?.title" width="720px" top="6vh">
      <div v-if="detail">
        <div v-for="s in detail.sections" :key="s.id" class="detail-section">
          <h4>{{ s.title }}</h4>
          <div v-for="(q, qi) in s.questions" :key="q.id" class="detail-question">
            <div class="q-meta">
              <b>{{ globalNumber(s, qi) }}.</b>
              <el-tag v-if="q.is_modified" size="small" type="warning">已修改</el-tag>
            </div>
            <div class="q-content" v-html="renderPreview(q.content, 400)"></div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-tooltip content="阶段二开放" placement="top">
          <el-button type="primary" disabled>进入编辑器</el-button>
        </el-tooltip>
        <el-button @click="showDetail = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { renderPreview } from '../utils/render'

const practices = ref([])
const showRename = ref(false)
const renameTitle = ref('')
const renameTarget = ref(null)
const showDetail = ref(false)
const detail = ref(null)

const load = async () => {
  const res = await axios.get('/api/practices')
  practices.value = res.data.practices
}

const formatTime = (t) => t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : ''

const globalNumber = (section, idx) => {
  // 只读预览用：按小节顺序连续编号（与后续编辑器的编号规则一致）
  let n = 0
  for (const s of detail.value.sections) {
    if (s.id === section.id) return n + idx + 1
    n += s.questions.length
  }
  return idx + 1
}

const openDetail = async (p) => {
  const res = await axios.get(`/api/practices/${p.id}`)
  detail.value = res.data
  showDetail.value = true
}

const rename = (p) => {
  renameTarget.value = p
  renameTitle.value = p.title
  showRename.value = true
}

const doRename = async () => {
  if (!renameTitle.value.trim()) return
  await axios.put(`/api/practices/${renameTarget.value.id}`, { title: renameTitle.value.trim() })
  showRename.value = false
  ElMessage.success('已重命名')
  await load()
}

const remove = async (p) => {
  await ElMessageBox.confirm(`确定删除练习“${p.title}”？删除后不可恢复。`, '提示', { type: 'warning' })
  await axios.delete(`/api/practices/${p.id}`)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.practice-list-view { max-width: 1100px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.subtitle { color: #909399; }
.practice-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.practice-card { cursor: pointer; }
.card-title { display: flex; justify-content: space-between; align-items: center; font-weight: bold; margin-bottom: 8px; }
.card-meta { display: flex; gap: 8px; color: #606266; font-size: 13px; margin-bottom: 8px; }
.card-footer { display: flex; justify-content: space-between; align-items: center; }
.card-time { color: #909399; font-size: 12px; }
.detail-section { margin-bottom: 16px; }
.detail-question { padding: 8px 0; border-bottom: 1px dashed #ebeef5; }
.q-meta { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.q-content { color: #303133; font-size: 14px; }
.q-content :deep(img) { max-height: 100px; }
</style>
```

- [ ] **Step 2: 路由与导航**

`router/index.js` 在 `/basket` 之后追加：

```js
  {
    path: '/practices',
    name: 'Practices',
    component: () => import('../views/PracticeListView.vue'),
  },
```

`App.vue` 侧边栏“选题池”之后插入：

```html
        <el-menu-item index="/practices">
          <el-icon><Notebook /></el-icon>
          <span>练习</span>
        </el-menu-item>
```

- [ ] **Step 3: 构建验证**（同 Task 7 Step 4）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/PracticeListView.vue frontend/src/router/index.js frontend/src/App.vue
git commit -m "feat: 练习列表页（查看/重命名/删除）"
```

---

### Task 10: 端到端验收 + 回归 + 收尾提交

**Files:** 无新增，仅验证。

- [ ] **Step 1: 全量后端测试**

Run: `cd backend ; conda run -n question_platform python -m pytest tests -q`
Expected: 全部 PASS（含原有 test_models / test_ocr_regression）

- [ ] **Step 2: 对真实库执行迁移并重启后端**

```
cd backend
conda run -n question_platform python -m alembic upgrade head
```

重启后端服务（迁移与路由变更均需重启生效）。

- [ ] **Step 3: 前端构建**（同 Task 7 Step 4）

- [ ] **Step 4: 手工验收规格场景一**

1. 题库页勾选若干题 → 点“加入选题池”，提示新增数量与池内总数。
2. 重复加入同一批题 → 提示均已在池中（added=0）。
3. 刷新页面 → 选题池数量保留（持久化，决策 7）。
4. 进入选题池页：题型统计正确；移除一题；上移/下移生效；回到题库补选一题。
5. 创建练习：填标题，勾选清空选题池 → 跳转练习列表，选题池已空。
6. 练习列表：卡片显示题数；点卡片看只读详情，小节按题型分组、图片正常显示（资产 URL 可访问）；重命名、删除生效（且 `data/practices/<id>` 目录被删）。
7. 确认题库原题未被修改（详情内容与加入前一致，零侵入）。

- [ ] **Step 5: 收尾提交（如有收尾修改）并确认 git 状态干净**

```bash
git status
git log --oneline -12
```

---

## 阶段一验收对照（规格第 14 章场景一）

| 场景一步骤 | 覆盖任务 |
|---|---|
| 筛选选题（学科/年级/难度/标签等） | 现有题库页 + Task 6 有答案筛选 |
| 加入选题池 | Task 2 + Task 7 |
| 刷新后仍存在 | Task 1（DB 持久化）+ Task 10 验证 |
| 移除一题并补选一题 | Task 2 + Task 8 |
| 创建练习、按题型分组、快照独立于题库 | Task 3-5 + Task 8/9 |

## Assumptions

- SQLite 不支持 `nullslast()`，列表排序统一用 `created_at desc`。
- `source_question_id` 不设数据库外键，快照在原题删除后仍可展示。
- 阶段一不提供空练习创建（创建必须有题目），编辑器入口在阶段二开放。
- `PracticeContentBlock` 阶段一仅建表，无读写接口。
- 题型映射前端工具与后端 `QUESTION_TYPE_MAP` 手工保持同步（新增题型时两处都要改）。
