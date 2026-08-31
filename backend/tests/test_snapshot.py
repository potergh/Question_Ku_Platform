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


async def test_create_assigns_consecutive_numbers(test_db, tmp_path, monkeypatch):
    """创建时即连续编号：不保留题库原卷号（用户决策 2026-08-30）。"""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    q_choice = await _make_source_with_figure(test_db, tmp_path)
    async with test_db() as db:
        q_choice = await db.get(Question, q_choice.id)
        q_choice.question_number = 7   # 故意不连续的原卷号
        q_fill = Question(
            source_id=q_choice.source_id, source_question_id="Q2", question_number=3,
            question_type="fill_blank", content="填空题干",
        )
        db.add(q_fill)
        await db.commit()
        await db.refresh(q_fill)
        await db.refresh(q_choice)   # updated_at 等服务端字段刷新，避免快照时懒加载
        practice = await practice_service.create_practice_from_questions(
            db, title="编号测试", subtitle=None, subject=None, grade=None,
            questions=[q_choice, q_fill],
        )
        nums = [pq.question_number for s in practice.sections for pq in s.questions]
        assert nums == [1, 2]


async def test_content_ocr_assets_ref_migrated_at_creation(test_db, tmp_path, monkeypatch):
    """题干里 /api/ocr-assets/… 形式的引用也在创建时迁入练习资产（否则渲染成 Markdown 文本）。"""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    q = await _make_source_with_figure(test_db, tmp_path)
    async with test_db() as db:
        q = await db.get(Question, q.id)
        q.content = f"题干 ![figure](/api/ocr-assets/{q.source_id}/figures/test_fig.webp) 结尾"
        await db.commit()
        await db.refresh(q)
        practice = await practice_service.create_practice_from_questions(
            db, title="引用测试", subtitle=None, subject=None, grade=None, questions=[q],
        )
        pq = practice.sections[0].questions[0]
        assert "asset://practice/" in pq.content_snapshot
        assert "/api/ocr-assets/" not in pq.content_snapshot
        assert "/figures/test_fig.webp" not in pq.content_snapshot
        assets = list(practice_service.practice_assets_dir(practice.id).glob("*_test_fig.webp"))
        assert len(assets) == 1
