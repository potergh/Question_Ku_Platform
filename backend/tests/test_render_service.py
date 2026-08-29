"""HTML 组装单测：不经浏览器，直接断言 HTML 文本。"""

from test_blocks_api import _create_practice
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
