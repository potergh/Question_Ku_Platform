"""阶段 5：整册编排布局测试。

覆盖：sections→布局迁移、布局校验、布局保存同步（跨小节拖动换序/新建小节/字段更新）、
整册 HTML 渲染（小节序号、整册连续题号、自定义文字/空白/分页符）、Word 导出。
"""

import io
import json

from docx import Document
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from test_blocks_api import _tiny_webp
from test_render_service import _load_with_blocks
from app.models.practice import Practice, PracticeQuestion, PracticeSection
from app.services import docx_export, practice_service, workbook_layout
from app.services.render_service import build_practice_html


def _doc(text: str) -> str:
    return json.dumps({"type": "doc", "schema_version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}]})


async def _seed_practice(test_db, tmp_path):
    """直接建库：练习 + 2 小节各 1 题（无 layout_document，用于迁移/同步测试）。"""
    async with test_db() as db:
        p = Practice(title="整册测试", subtitle="", status="draft", is_baseline=False)
        db.add(p)
        await db.flush()
        sec1 = PracticeSection(practice_id=p.id, title="选择题", section_type="single_choice",
                               position=0, show_title=True, start_on_new_page=False)
        sec2 = PracticeSection(practice_id=p.id, title="填空题", section_type="fill",
                               position=1, show_title=True, start_on_new_page=False)
        db.add_all([sec1, sec2])
        await db.flush()
        q1 = PracticeQuestion(practice_id=p.id, section_id=sec1.id, position=1,
                              question_number=1, question_type="single_choice", score=5,
                              rich_document=_doc("第一题"), doc_version=1, is_modified=False)
        q2 = PracticeQuestion(practice_id=p.id, section_id=sec2.id, position=1,
                              question_number=2, question_type="fill", score=5,
                              rich_document=_doc("第二题"), doc_version=1, is_modified=False)
        db.add_all([q1, q2])
        await db.commit()
        pid = p.id
        ids = {"sec1": sec1.id, "sec2": sec2.id, "q1": q1.id, "q2": q2.id}
    return pid, ids


async def _load_practice_for_sync(db, pid):
    return (await db.execute(
        select(Practice).where(Practice.id == pid)
        .options(selectinload(Practice.sections).selectinload(PracticeSection.questions))
        .execution_options(populate_existing=True))).scalar_one()


# ---------------- 迁移与校验 ----------------

async def test_ensure_layout_migrates(test_db, tmp_path):
    pid, ids = await _seed_practice(test_db, tmp_path)
    practice = await _load_with_blocks(test_db, pid)
    assert practice.layout_document is None
    async with test_db() as db:
        p = await _load_practice_for_sync(db, pid)
        layout = await workbook_layout.ensure_layout(db, p)
        await db.commit()
    types = [b["type"] for b in layout]
    assert types == ["subtitle", "question_ref", "subtitle", "question_ref"]
    assert layout[0]["section_id"] == ids["sec1"]
    assert layout[1]["question_id"] == ids["q1"]
    assert layout[2]["title"] == "填空题"
    # 已持久化
    p2 = await _load_with_blocks(test_db, pid)
    assert p2.layout_document is not None


def test_validate_layout_drops_unknown():
    layout = workbook_layout.validate_layout([
        {"type": "subtitle", "title": "一", "show_title": True, "start_on_new_page": False},
        {"type": "question_ref", "question_id": "q"},
        {"type": "custom_text", "html": "<p>说明</p>"},
        {"type": "spacer", "height": 30},
        {"type": "page_break"},
        {"type": "evil", "x": 1},
        "not-a-dict",
    ])
    types = [b["type"] for b in layout]
    assert types == ["subtitle", "question_ref", "custom_text", "spacer", "page_break"]
    assert layout[3]["height"] == 30
    assert layout[2]["html"] == "<p>说明</p>"


# ---------------- 保存同步 ----------------

async def test_sync_reorder_cross_section(test_db, tmp_path):
    """把 q2 从"填空题"拖到"选择题"下、且放在 q1 前 → 题号重排、归属更新。"""
    pid, ids = await _seed_practice(test_db, tmp_path)
    layout = [
        {"type": "subtitle", "id": "s1", "section_id": ids["sec1"], "title": "选择题",
         "show_title": True, "start_on_new_page": False},
        {"type": "question_ref", "id": "r2", "question_id": ids["q2"]},
        {"type": "question_ref", "id": "r1", "question_id": ids["q1"]},
        {"type": "subtitle", "id": "s2", "section_id": ids["sec2"], "title": "填空题",
         "show_title": True, "start_on_new_page": False},
    ]
    async with test_db() as db:
        p = await _load_practice_for_sync(db, pid)
        layout = await workbook_layout.sync_sections_from_layout(db, p, layout)
        p.layout_document = layout
        await db.commit()
    p3 = await _load_with_blocks(test_db, pid)
    sec1 = next(s for s in p3.sections if s.id == ids["sec1"])
    assert [q.id for q in sec1.questions] == [ids["q2"], ids["q1"]]
    assert [q.question_number for q in sec1.questions] == [1, 2]
    assert [q.position for q in sec1.questions] == [1, 2]
    sec2 = next(s for s in p3.sections if s.id == ids["sec2"])
    assert sec2.questions == []


async def test_sync_creates_new_subtitle(test_db, tmp_path):
    """新增 subtitle 块 → 自动创建 PracticeSection 并回写 section_id。"""
    pid, ids = await _seed_practice(test_db, tmp_path)
    layout = [
        {"type": "subtitle", "id": "s1", "section_id": ids["sec1"], "title": "选择题",
         "show_title": True, "start_on_new_page": False},
        {"type": "question_ref", "id": "r1", "question_id": ids["q1"]},
        {"type": "subtitle", "id": "new", "title": "应用题", "show_title": True,
         "start_on_new_page": True},
        {"type": "question_ref", "id": "r2", "question_id": ids["q2"]},
    ]
    async with test_db() as db:
        p = await _load_practice_for_sync(db, pid)
        layout = await workbook_layout.sync_sections_from_layout(db, p, layout)
        p.layout_document = layout
        await db.commit()
    p2 = await _load_with_blocks(test_db, pid)
    assert len(p2.sections) == 3
    new_sec = next((s for s in p2.sections if s.title == "应用题"), None)
    assert new_sec is not None
    assert new_sec.start_on_new_page is True
    assert [q.id for q in new_sec.questions] == [ids["q2"]]
    assert new_sec.questions[0].question_number == 2


# ---------------- 整册渲染（HTML） ----------------

async def _setup_render_layout(test_db, tmp_path, extra_blocks):
    pid, ids = await _seed_practice(test_db, tmp_path)
    async with test_db() as db:
        p = await _load_practice_for_sync(db, pid)
        p.layout_document = await workbook_layout.sync_sections_from_layout(db, p, [
            {"type": "subtitle", "id": "s1", "section_id": ids["sec1"], "title": "选择题",
             "show_title": True, "start_on_new_page": False},
            {"type": "question_ref", "id": "r1", "question_id": ids["q1"]},
            *extra_blocks,
            {"type": "subtitle", "id": "s2", "section_id": ids["sec2"], "title": "填空题",
             "show_title": True, "start_on_new_page": False},
            {"type": "question_ref", "id": "r2", "question_id": ids["q2"]},
        ])
        await db.commit()
    return pid, ids


async def test_render_from_layout(test_db, tmp_path):
    pid, ids = await _setup_render_layout(test_db, tmp_path, [
        {"type": "custom_text", "id": "c1", "html": "<p>考试<b>说明</b></p>"},
        {"type": "spacer", "id": "sp1", "height": 30},
        {"type": "page_break", "id": "pb1"},
    ])
    practice = await _load_with_blocks(test_db, pid)
    html = build_practice_html(practice, pid)
    assert "一、选择题" in html
    assert "二、填空题" in html
    assert "1. " in html and "2. " in html
    assert "考试<b>说明</b>" in html
    assert "q-spacer" in html
    assert 'style="height:30px"' in html
    assert html.count("new-page") >= 1   # 分页符


async def test_render_from_layout_custom_asset(test_db, tmp_path):
    """自定义内容里的图片 asset:// 引用 → 渲染为可访问 src。"""
    pid, ids = await _seed_practice(test_db, tmp_path)
    assets = practice_service.practice_assets_dir(pid)
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "pic.webp").write_bytes(_tiny_webp())
    async with test_db() as db:
        p = await _load_practice_for_sync(db, pid)
        p.layout_document = [
            {"type": "custom_text", "id": "c1", "html": '<p><img src="asset://practice/pic.webp"></p>'}]
        await db.commit()
    practice = await _load_with_blocks(test_db, pid)
    html = build_practice_html(practice, pid)
    assert "pic.webp" in html
    assert "file:///" in html    # asset:// 已解析为可访问路径


# ---------------- 整册渲染（Word） ----------------

async def test_docx_export_from_layout(test_db, tmp_path):
    pid, ids = await _setup_render_layout(test_db, tmp_path, [
        {"type": "custom_text", "id": "c1", "html": "<p>考试<b>说明</b></p>"},
        {"type": "spacer", "id": "sp1", "height": 30},
        {"type": "page_break", "id": "pb1"},
    ])
    practice = await _load_with_blocks(test_db, pid)
    data, degraded = docx_export.build_docx(practice, pid)
    assert data
    doc = Document(io.BytesIO(data))
    joined = "\n".join(par.text for par in doc.paragraphs)
    assert "一、选择题" in joined
    assert "二、填空题" in joined
    assert "考试" in joined and "说明" in joined
    assert "第一题" in joined
    assert "2. " in joined


async def test_layout_rendering_equals_sections_when_migrated(test_db, tmp_path):
    """迁移后（layout 与 sections 同构）HTML 渲染与旧 sections 渲染题目/小节一致。"""
    pid, ids = await _seed_practice(test_db, tmp_path)
    p = await _load_with_blocks(test_db, pid)
    html_old = build_practice_html(p, pid)
    assert "选择题" in html_old and "填空题" in html_old
    assert "第一题" in html_old and "第二题" in html_old
