"""HTML 组装单测：不经浏览器，直接断言 HTML 文本。"""

from docx import Document
import io

from test_blocks_api import _create_practice
from app.services import docx_export
from app.services.render_service import build_practice_html, render_settings


async def _full_practice(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    detail = (await client.get(f"/api/practices/{practice['id']}/detail")).json()
    return detail


async def _load_with_blocks(test_db, pid):
    """test_db 是 session 工厂；直接查测试库，勿用生产 get_db。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.practice import Practice, PracticeSection, PracticeQuestion
    async with test_db() as db:
        return (await db.execute(
            select(Practice).where(Practice.id == pid)
            .options(selectinload(Practice.sections)
                     .selectinload(PracticeSection.questions)
                     .selectinload(PracticeQuestion.blocks))
            .execution_options(populate_existing=True)
        )).scalar_one()


def test_render_settings_defaults():
    class FakePractice:
        page_config = None
    s = render_settings(FakePractice())
    assert s["margin"] == "25mm"
    assert s["show_info_bar"] is True
    assert s["show_page_number"] is True
    assert s["show_score"] is False


async def test_build_html_contains_structure(client, test_db, tmp_path):
    detail = await _full_practice(client, test_db, tmp_path)
    practice = await _load_with_blocks(test_db, detail["id"])
    html = build_practice_html(practice, detail["id"])
    assert detail["title"] in html
    assert "姓名" in html                      # 默认显示学生信息栏
    assert "1." in html                        # 题号
    assert "q-option" in html                  # 单选题必带选项块
    assert "answer-space" in html              # 留白块
    assert "katex" in html                     # KaTeX 标签


async def test_build_html_respects_page_config(client, test_db, tmp_path):
    detail = await _full_practice(client, test_db, tmp_path)
    pid = detail["id"]
    await client.put(f"/api/practices/{pid}", json={"title": detail["title"],
        "page_config": {"show_info_bar": False, "show_score": True, "margin_preset": "narrow"}})
    practice = await _load_with_blocks(test_db, pid)
    html = build_practice_html(practice, pid)
    settings = render_settings(practice)
    assert "姓名" not in html                  # 信息栏关闭
    assert settings["margin"] == "15mm"


async def test_prefix_inline_and_img_row(client, test_db, tmp_path):
    """题号并入题干首行；连续多图并排一行（HTML 与 Word 一致）。"""
    # 连续两图 → materialize 出两个相邻 image 块（题号 3 顺带验证重排为 1）
    from app.models import Source, Question
    from test_blocks_api import _tiny_webp
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True, exist_ok=True)
    (ocr_dir / "figures" / "f.webp").write_bytes(_tiny_webp())
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q1", question_number=3,
                     question_type="short_answer",
                     content="题干首行\n![图](asset://figures/f.webp)![图](asset://figures/f.webp)",
                     options=None)
        db.add(q)
        await db.commit()
        await db.refresh(q)
        qid = q.id
    practice = (await client.post("/api/practices", json={
        "title": "t", "from_basket": False, "question_ids": [qid]})).json()
    pid = practice["id"]
    await client.get(f"/api/practices/{pid}/detail")   # 懒物化 + 重排题号 3→1
    p = await _load_with_blocks(test_db, pid)

    html = build_practice_html(p, pid)
    assert '<div class="q-text"><b>1. </b>题干首行</div>' in html   # 题号与题干同行（无 ![图]( 残留）
    assert "q-img-row" in html                                       # 连续两图并排
    assert html.count('<div class="q-img-cell">') == 2

    doc = Document(io.BytesIO(docx_export.build_docx(p, pid)))
    texts = [para.text for para in doc.paragraphs]
    assert "1. 题干首行" in texts                                    # Word 同样同行（且已重排）
    assert any(len(t.rows[0].cells) == 2 for t in doc.tables)        # 两图用单行表格并排
