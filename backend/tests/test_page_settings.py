"""阶段 6：页面样式、页眉页脚（方向/自定义边距/变量解析/页眉页脚模板/Word 字段与首页不同）。"""

import io
import json
import re
import zipfile

import pytest

from app.models.practice import Practice, PracticeSection, PracticeQuestion
from app.services import render_service as rs
from app.services.docx_export import build_docx


def _practice(page_config=None, **kw):
    return Practice(title="测试练习", subject="物理", grade="中考",
                    page_config=page_config, **kw)


def test_legacy_page_config_no_header():
    """旧练习（无 header/footer 键）→ 无页眉、footer=None（沿用旧页码行为）。"""
    s = rs.render_settings(_practice({"show_page_number": True}))
    assert s["header"]["enabled"] is False
    assert s["footer"] is None
    assert s["margins"] == {"top": 25.0, "bottom": 25.0, "left": 25.0, "right": 25.0}


def test_new_page_config_defaults():
    s = rs.render_settings(_practice({
        "header": {"enabled": True, "center": "{title}"},
        "footer": {"enabled": True, "center": "{page} / {total}"},
        "orientation": "landscape",
    }))
    assert s["orientation"] == "landscape"
    assert s["header"]["center"] == "测试练习"
    assert s["footer"]["center"] == "{page} / {total}"


def test_custom_margins():
    s = rs.render_settings(_practice({
        "margin_preset": "custom",
        "margins": {"top": 20, "bottom": 15, "left": 18, "right": 30},
    }))
    assert s["margins"] == {"top": 20.0, "bottom": 15.0, "left": 18.0, "right": 30.0}


def test_resolve_page_vars():
    p = _practice({"variables": {"school": "一中", "teacher": "张老师"}})
    out = rs._resolve_page_vars("{title}|{school}|{teacher}|{date}|{page}",
                                p, {"school": "一中", "teacher": "张老师"})
    assert "测试练习" in out
    assert "一中" in out and "张老师" in out
    assert "2026-" in out or re.match(r".*\d{4}-\d{2}-\d{2}.*", out)
    assert "{page}" in out   # 页码占位保留，由 PDF/Word 各自处理


def test_hf_template_and_frag():
    zone = {"left": "", "center": "第 {page} 页", "right": "{total}",
            "font_size": 9, "line": True}
    tpl = rs._hf_template(zone, top=True)
    assert '<span class="pageNumber">' in tpl
    assert '<span class="totalPages">' in tpl
    assert "border-bottom" in tpl
    assert 'text-align:left' in tpl and 'text-align:center' in tpl and 'text-align:right' in tpl
    assert rs._hf_frag("第 {page} 页") == '第 <span class="pageNumber"></span> 页'


async def _seed_hf_practice(test_db, tmp_path, monkeypatch):
    """建一个带阶段 6 页面配置的练习（横向、自定义边距、三栏页眉页脚、首页隐藏页眉）。"""
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    async with test_db() as db:
        p = Practice(title="页眉测试", subject="物理", grade="中考", status="draft", is_baseline=False,
                     page_config={
                         "orientation": "landscape",
                         "margins": {"top": 20, "bottom": 18, "left": 22, "right": 22},
                         "variables": {"school": "一中", "teacher": "张老师"},
                         "header": {"enabled": True, "left": "{school}", "center": "{title}",
                                    "right": "{teacher}", "font_size": 9, "distance": 8, "line": True,
                                    "first_page_different": True, "first_hidden": True},
                         "footer": {"enabled": True, "left": "", "center": "第 {page} 页 / 共 {total} 页",
                                    "right": "", "font_size": 9, "distance": 8, "line": False,
                                    "first_hidden": False},
                     })
        db.add(p)
        await db.flush()
        sec = PracticeSection(practice_id=p.id, title="选择题", section_type="single_choice",
                              position=0, show_title=True, start_on_new_page=False)
        db.add(sec)
        await db.flush()
        q = PracticeQuestion(practice_id=p.id, section_id=sec.id, position=1, question_number=1,
                             question_type="single_choice", score=5,
                             rich_document=json.dumps({"type": "doc", "content": [
                                 {"type": "paragraph", "content": [
                                     {"type": "text", "text": "第一题"}]}]}),
                             doc_version=1, is_modified=False)
        db.add(q)
        await db.commit()
        r = await db.execute(
            select(Practice).where(Practice.id == p.id)
            .options(selectinload(Practice.sections).selectinload(PracticeSection.questions)))
        return r.scalar_one(), p.id


@pytest.mark.asyncio
async def test_docx_header_footer_orientation_firstpage(test_db, tmp_path, monkeypatch):
    p, pid = await _seed_hf_practice(test_db, tmp_path, monkeypatch)
    data, degraded = build_docx(p, pid)
    assert degraded == []
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()

    # 页眉三栏 + 分隔线 + 变量替换
    hdr = [n for n in names if n.endswith("header1.xml")]
    assert hdr, "主页眉缺失"
    x = z.read(hdr[0]).decode("utf-8")
    texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", x)
    assert "一中" in texts and "页眉测试" in texts and "张老师" in texts
    assert "w:pBdr" in x   # 分隔线

    # 页脚：PAGE + NUMPAGES 域
    ftr = [n for n in names if n.endswith("footer1.xml")]
    assert ftr, "主页脚缺失"
    xf = z.read(ftr[0]).decode("utf-8")
    assert "PAGE" in xf and "NUMPAGES" in xf

    # 首页不同：titlePg + 独立空首页页眉/页脚
    doc_x = z.read("word/document.xml").decode("utf-8")
    assert "landscape" in doc_x   # 横向
    assert "titlePg" in doc_x
    first_hdr = [n for n in names if n.endswith("header2.xml")]
    assert first_hdr, "首页页眉 part 缺失（否则首页会沿用主页眉）"
    fh = z.read(first_hdr[0]).decode("utf-8")
    assert "<w:t" not in fh or "页眉测试" not in fh   # 首页页眉为空
