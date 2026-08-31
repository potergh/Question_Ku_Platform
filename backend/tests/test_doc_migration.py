"""阶段 0 Task 0.6：旧练习迁移回归测试（保真 / 幂等 / 失败隔离 / 可重试 / 试运行不落库）。"""

import argparse
import importlib.util
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.practice import Practice, PracticeContentBlock, PracticeQuestion
from app.services import doc_migration
from test_blocks_api import _create_practice
from test_structure_api import _two_questions


def _doc(pq) -> dict:
    assert pq.rich_document is not None
    return json.loads(pq.rich_document)


async def _migrate(test_db, practice_id: str) -> dict:
    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice_id)
        res = await doc_migration.migrate_practice(db, p)
        await db.commit()
    return res


async def test_migrate_generates_doc_for_every_question(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    res = await _migrate(test_db, practice["id"])
    assert res["questions"] == 2
    assert res["warnings"] == []

    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice["id"])
        assert p.migration_status == "done"
        assert p.migrated_at is not None
        for sec in p.sections:
            for pq in sec.questions:
                assert pq.doc_version == 1
                doc = _doc(pq)
                assert doc["type"] == "doc"
                assert doc["content"]  # 非空文档


async def test_migrate_keeps_text_options_and_order(client, test_db, tmp_path):
    """题干文字、选项与顺序不得丢失。"""
    practice = await _two_questions(client, test_db, tmp_path)
    await _migrate(test_db, practice["id"])

    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice["id"])
        questions = [pq for sec in sorted(p.sections, key=lambda s: s.position)
                     for pq in sorted(sec.questions, key=lambda q: q.position)]
        q1, q2 = questions
        # 选择题：题干段落 + 选项组，且顺序为题干在前
        types1 = [n["type"] for n in _doc(q1)["content"]]
        assert types1[0] == "paragraph"
        assert "optionGroup" in types1
        text1 = "".join(n.get("text", "") for n in _doc(q1)["content"][0]["content"])
        assert "选择题题干" in text1
        # 填空题：题干段落 + 默认答题留白（题型决定）
        types2 = [n["type"] for n in _doc(q2)["content"]]
        assert types2[0] == "paragraph"
        assert "answerSpace" in types2
        text2 = "".join(n.get("text", "") for n in _doc(q2)["content"][0]["content"])
        assert "填空题题干" in text2


async def test_migrate_keeps_inline_image(client, test_db, tmp_path):
    """行内图片引用必须保留为图片节点（不得丢失）。"""
    practice = await _create_practice(client, test_db, tmp_path)
    await _migrate(test_db, practice["id"])

    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice["id"])
        pq = p.sections[0].questions[0]
        doc = _doc(pq)
        # 独立图片块是文档顶层节点；行内引用在段落内部，两者都要算上
        nodes = [n for blk in doc["content"] for n in blk.get("content", [])]
        img_nodes = ([n for n in doc["content"] if n["type"] in ("image", "inlineImage")]
                     + [n for n in nodes if n["type"] in ("image", "inlineImage")])
        assert len(img_nodes) == 1
        assert "f.webp" in img_nodes[0]["attrs"]["src"]


async def test_migrate_does_not_touch_legacy_fields(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)

    async with test_db() as db:
        before = {}
        for pq in (await db.execute(select(PracticeQuestion)
                                    .where(PracticeQuestion.practice_id == practice["id"]))).scalars():
            before[pq.id] = (pq.content_snapshot, pq.options_snapshot, pq.is_modified)
    await _migrate(test_db, practice["id"])
    async with test_db() as db:
        for pq in (await db.execute(select(PracticeQuestion)
                                    .where(PracticeQuestion.practice_id == practice["id"]))).scalars():
            assert (pq.content_snapshot, pq.options_snapshot, pq.is_modified) == before[pq.id]


async def test_migrate_is_idempotent(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    await _migrate(test_db, practice["id"])

    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice["id"])
        first = {pq.id: pq.rich_document for sec in p.sections for pq in sec.questions}

    # 重复执行：结果必须完全一致，不产生重复节点
    await _migrate(test_db, practice["id"])
    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice["id"])
        for sec in p.sections:
            for pq in sec.questions:
                assert pq.rich_document == first[pq.id]


async def test_dry_run_does_not_write(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice["id"])
        res = await doc_migration.dry_run_practice(db, p)
        await db.rollback()
    assert res["questions"] == 2

    async with test_db() as db:
        p = await doc_migration.load_practice_for_migration(db, practice["id"])
        assert p.migration_status != "done"
        for sec in p.sections:
            for pq in sec.questions:
                assert pq.rich_document is None
                assert pq.doc_version == 0
        n_blocks = (await db.execute(
            select(PracticeContentBlock).where(
                PracticeContentBlock.practice_question_id.in_(
                    [pq.id for sec in p.sections for pq in sec.questions])))).scalars().all()
        assert n_blocks == []  # 试运行不得物化内容块


async def test_new_practice_marked_native(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    async with test_db() as db:
        p = await db.get(Practice, practice["id"])
        assert p.migration_status == "native"


def test_make_backup_copies_db_and_practices(tmp_path):
    """--apply 前自动备份：数据库文件与练习资产目录都要进备份。"""
    script = Path(__file__).resolve().parent.parent / "scripts" / "phase0_migrate.py"
    spec = importlib.util.spec_from_file_location("phase0_migrate_tool_bak", script)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    data_dir = tmp_path / "data"
    (data_dir / "practices" / "p1" / "assets").mkdir(parents=True)
    (data_dir / "practices" / "p1" / "assets" / "a.webp").write_bytes(b"img")
    db_path = data_dir / "db.sqlite3"
    db_path.write_bytes(b"sqlite-data")

    dest = tool.make_backup(data_dir, db_path)
    assert dest is not None and dest.exists()
    assert (dest / "db.sqlite3").read_bytes() == b"sqlite-data"
    assert (dest / "practices" / "p1" / "assets" / "a.webp").read_bytes() == b"img"


async def test_script_failure_isolation_and_retry(tmp_path, monkeypatch):
    """单份失败不阻断其他练习；失败练习保留旧数据，可用 --practice 重试。"""
    script = Path(__file__).resolve().parent.parent / "scripts" / "phase0_migrate.py"
    spec = importlib.util.spec_from_file_location("phase0_migrate_tool", script)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    db_path = tmp_path / "migrate.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}",
                                 connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        pa, pb = Practice(title="A"), Practice(title="B")
        db.add_all([pa, pb])
        await db.commit()
        id_a, id_b = pa.id, pb.id
    monkeypatch.setattr(settings, "db_path", db_path)

    orig = doc_migration.migrate_practice

    async def boom(db, practice):
        if practice.id == id_a:
            raise RuntimeError("模拟故障")
        return await orig(db, practice)
    monkeypatch.setattr(doc_migration, "migrate_practice", boom)

    args = argparse.Namespace(apply=True, practice=None, no_backup=True, db=None, data_dir=None)
    report = await tool.run(args)
    by_id = {e["id"]: e for e in report["practices"]}
    assert by_id[id_a]["status"] == "failed"
    assert by_id[id_b]["status"] == "done"

    async with factory() as db:
        a = await db.get(Practice, id_a)
        assert a.migration_status == "failed"
        assert "模拟故障" in a.migration_note
        b = await db.get(Practice, id_b)
        assert b.migration_status == "done"

    # 重试：恢复正常迁移逻辑，只处理失败的那份
    monkeypatch.setattr(doc_migration, "migrate_practice", orig)
    args2 = argparse.Namespace(apply=True, practice=id_a, no_backup=True, db=None, data_dir=None)
    report2 = await tool.run(args2)
    assert len(report2["practices"]) == 1
    assert report2["practices"][0]["status"] == "done"
    async with factory() as db:
        a = await db.get(Practice, id_a)
        assert a.migration_status == "done"
        assert a.migration_note is None
    await engine.dispose()
