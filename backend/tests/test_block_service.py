"""Block service tests — materialize / rebuild / restore."""

from app.models import Source, Question
from app.models.practice import PracticeQuestion
from app.services import practice_service, block_service
from sqlalchemy import select


async def _make_practice(test_db, tmp_path, monkeypatch):
    """造一个带图选择题的练习，返回 practice。"""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True)
    (ocr_dir / "figures" / "f.webp").write_bytes(b"img")

    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                     question_type="single_choice",
                     content="题干第一段 ![图](asset://figures/f.webp) 题干第二段",
                     options=[{"label": "A", "content": "x"}, {"label": "B", "content": "y"}])
        db.add(q)
        await db.commit()
        await db.refresh(q)
        practice = await practice_service.create_practice_from_questions(
            db, "t", None, None, None, [q])
        return practice


async def test_materialize_blocks(test_db, tmp_path, monkeypatch):
    practice = await _make_practice(test_db, tmp_path, monkeypatch)
    async with test_db() as db:
        pq = (await db.execute(select(PracticeQuestion))).scalars().first()
        blocks = await block_service.materialize_blocks(db, pq)
        types = [b.block_type for b in blocks]
        assert types == ["text", "image", "text", "options", "answer_space"]
        assert "asset://practice/" in blocks[1].content
        import json as _json
        assert _json.loads(blocks[3].content) == [
            {"label": "A", "content": "x"}, {"label": "B", "content": "y"}]
        assert blocks[0].position == 0 and blocks[4].position == 4
        # 幂等
        again = await block_service.materialize_blocks(db, pq)
        assert [b.id for b in again] == [b.id for b in blocks]


async def test_rebuild_content(test_db, tmp_path, monkeypatch):
    practice = await _make_practice(test_db, tmp_path, monkeypatch)
    async with test_db() as db:
        pq = (await db.execute(select(PracticeQuestion))).scalars().first()
        blocks = await block_service.materialize_blocks(db, pq)
        blocks[0].content = "修改后的题干"
        await db.commit()
        await block_service.rebuild_content_from_blocks(db, pq)
        await db.commit()
        assert pq.is_modified is True
        assert pq.content_snapshot.startswith("修改后的题干")
        assert "asset://practice/" in pq.content_snapshot
        assert "题干第二段" in pq.content_snapshot


async def test_restore_from_source(test_db, tmp_path, monkeypatch):
    practice = await _make_practice(test_db, tmp_path, monkeypatch)
    async with test_db() as db:
        pq = (await db.execute(select(PracticeQuestion))).scalars().first()
        blocks = await block_service.materialize_blocks(db, pq)
        blocks[0].content = "被改坏了"
        await db.commit()
        await block_service.rebuild_content_from_blocks(db, pq)
        await db.commit()

        restored = await block_service.restore_question_from_source(db, pq)
        assert restored.is_modified is False
        assert "题干第一段" in restored.content_snapshot
        # restored 由服务内部以 selectinload 重新加载，可安全访问 blocks
        assert [b.block_type for b in restored.blocks] == ["text", "image", "text", "options", "answer_space"]
