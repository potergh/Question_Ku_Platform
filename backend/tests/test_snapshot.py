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
