"""Test that all models create correctly and relationships work."""

import pytest
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Source, Question, Tag, Settings, Job


# Use a separate in-memory DB for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=True)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db():
    async with TestSession() as session:
        yield session


# ── Source ─────────────────────────────────────────────

async def test_create_source(db: AsyncSession):
    source = Source(filename="test.pdf", file_path="/tmp/test.pdf", file_type="pdf", subject="物理")
    db.add(source)
    await db.commit()
    await db.refresh(source)
    assert source.id is not None
    assert source.ocr_status == "pending"
    assert source.question_count == 0


# ── Question ───────────────────────────────────────────

async def test_create_question_with_markdown_content(db: AsyncSession):
    """Question uses Markdown canonical: inline images + LaTeX."""
    source = Source(filename="test.pdf", file_path="/tmp/test.pdf", file_type="pdf")
    db.add(source)
    await db.commit()

    question = Question(
        source_id=source.id,
        source_question_id="Q001",
        question_number=1,
        question_type="选择题",
        subject="物理",
        difficulty=3,
        raw_ocr_content="如图所示，小球从A点滑下...",  # OCR original, never overwritten
        content="如图所示，小球从A点滑下...\n\n![figure](asset://figures/Q001_01.webp)\n\n若 $F=ma$，则加速度为____",
        options=[{"label": "A", "content": "1m/s²"}, {"label": "B", "content": "2m/s²"}],
        answer="B",
        explanation="由牛顿第二定律 $F=ma$ 可得...",
        score=5.0,
        needs_review=True,
        review_status="pending",
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)

    assert question.id is not None
    assert question.raw_ocr_content is not None
    assert "$F=ma$" in question.content
    assert "asset://figures" in question.content
    assert isinstance(question.options, list)
    assert len(question.options) == 2
    assert question.is_deleted is False


# ── Soft Delete ────────────────────────────────────────

async def test_soft_delete_question(db: AsyncSession):
    source = Source(filename="test.pdf", file_path="/tmp/test.pdf", file_type="pdf")
    db.add(source)
    await db.commit()

    question = Question(
        source_id=source.id,
        source_question_id="Q002",
        question_number=2,
        content="Test question",
    )
    db.add(question)
    await db.commit()

    # Soft delete
    question.is_deleted = True
    question.deleted_at = datetime.now()
    await db.commit()
    await db.refresh(question)

    assert question.is_deleted is True
    assert question.deleted_at is not None


# ── Tag ────────────────────────────────────────────────

async def test_tag_hierarchy(db: AsyncSession):
    parent = Tag(name="力学", category="knowledge", color="#ff0000")
    db.add(parent)
    await db.flush()  # Generate parent.id before creating child

    child = Tag(name="牛顿定律", category="knowledge", color="#ff0000", parent_id=parent.id)
    db.add(child)
    await db.commit()
    await db.refresh(child, ["parent"])

    assert child.parent_id == parent.id
    assert child.parent.name == "力学"


# ── Question ↔ Tag (N:M) ──────────────────────────────

async def test_question_tag_association(db: AsyncSession):
    source = Source(filename="test.pdf", file_path="/tmp/test.pdf", file_type="pdf")
    db.add(source)
    await db.commit()

    question = Question(
        source_id=source.id,
        source_question_id="Q003",
        question_number=3,
        content="Test",
    )
    tag = Tag(name="牛顿定律", category="knowledge")
    db.add_all([question, tag])
    await db.commit()

    # Eagerly load the tags relationship
    await db.refresh(question, ["tags"])
    question.tags.append(tag)
    await db.commit()
    await db.refresh(question, ["tags"])

    assert len(question.tags) == 1
    assert question.tags[0].name == "牛顿定律"


# ── Settings ───────────────────────────────────────────

async def test_settings_key_masking():
    assert Settings.mask_key("sk-1234567890abcdef") == "sk-1****cdef"
    assert Settings.mask_key("short") is None
    assert Settings.mask_key(None) is None


async def test_settings_model(db: AsyncSession):
    s = Settings(ai_mode="remote", ai_api_key="sk-1234567890", ai_model="gpt-4o")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    assert s.ai_mode == "remote"
    assert s.ai_temperature == 0.7


# ── Job ────────────────────────────────────────────────

async def test_job_lifecycle(db: AsyncSession):
    job = Job(job_type="ocr", status="queued")
    db.add(job)
    await db.commit()
    await db.refresh(job)

    assert job.status == "queued"
    assert job.progress == 0.0

    job.status = "running"
    job.progress = 50.0
    await db.commit()
    await db.refresh(job)
    assert job.status == "running"

