"""阶段 3：公式导出测试（OMML 原生 / 图片降级 / 降级清单头 / KaTeX 渲染器）。"""

import io
from urllib.parse import quote

from docx import Document

from test_blocks_api import _create_practice, _question
from test_render_service import _load_with_blocks
from test_typography import _save_doc
from app.services import docx_export
from app.services.render_service import build_practice_html


def _formula_doc(latex, display=False):
    node = {"type": "displayFormula" if display else "inlineFormula",
            "attrs": {"latex": latex}}
    return {"type": "doc", "schema_version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "题干："}]},
        ({"type": "paragraph", "content": [node]} if display else
         {"type": "paragraph", "content": [node]}),
    ]}


def _png_1x1() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, "PNG")
    return buf.getvalue()


async def test_top_level_display_formula_save_and_render(client, test_db, tmp_path):
    """验收回归：顶层独立公式保存通过（校验白名单），预览与 Word 均渲染。"""
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    doc = {"type": "doc", "schema_version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "结论："}]},
        {"type": "displayFormula", "attrs": {"latex": "E=mc^2"}},
        {"type": "paragraph", "content": [{"type": "text", "text": "完毕"}]},
    ]}
    res = await _save_doc(client, practice, q, doc)
    assert res.status_code == 200, res.text
    # 旧块反向双写：独立公式回迁为独占一行的 $$…$$
    assert any("$$E=mc^2$$" in (b["content"] or "") for b in res.json()["blocks"])
    # 预览 HTML 输出居中 $$ 定界符（KaTeX 自动渲染）
    p = await _load_with_blocks(test_db, practice["id"])
    html = build_practice_html(p, practice["id"])
    assert "q-formula" in html and "$$E=mc^2$$" in html
    # Word：OMML 行间公式对象；降级清单为空；顶层节点不再丢失
    data, degraded = docx_export.build_docx(p, practice["id"])
    assert "oMathPara" in Document(io.BytesIO(data)).element.xml
    assert degraded == []


async def test_formula_native_omml_no_degraded(client, test_db, tmp_path):
    """可转换公式保持 OMML 原生（可继续编辑），降级清单为空。"""
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    res = await _save_doc(client, practice, q, _formula_doc("a^2+b^2=c^2"))
    assert res.status_code == 200, res.text
    p = await _load_with_blocks(test_db, practice["id"])
    data, degraded = docx_export.build_docx(p, practice["id"])
    assert "oMath" in Document(io.BytesIO(data)).element.xml
    assert degraded == []


async def test_formula_fallback_image_and_header(client, test_db, tmp_path, monkeypatch):
    """OMML 转换失败 → 降级为图片（alt 保留 LaTeX）+ 导出响应头列出清单。"""
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    latex = "\\unsupportedmacro{x}"
    res = await _save_doc(client, practice, q, _formula_doc(latex))
    assert res.status_code == 200, res.text

    monkeypatch.setattr(docx_export, "_latex_to_omml", lambda tex, display: None)
    monkeypatch.setattr(docx_export._FormulaFallback, "render",
                        lambda self, tex, display: _png_1x1())

    # 直接调用：降级清单回传 + 图片带 LaTeX 替代文字
    p = await _load_with_blocks(test_db, practice["id"])
    data, degraded = docx_export.build_docx(p, practice["id"])
    assert degraded == [latex]
    doc = Document(io.BytesIO(data))
    assert any("descr" in sh._inline.xml and latex in sh._inline.xml
               for sh in doc.inline_shapes)

    # 端点：降级清单经 X-Formula-Degraded 头传递（URL 编码）
    res = await client.get(f"/api/practices/{practice['id']}/export/docx")
    assert res.status_code == 200
    assert quote(latex, safe="") in res.headers["x-formula-degraded"]


async def test_formula_fallback_render_failure_keeps_latex(client, test_db, tmp_path, monkeypatch):
    """图片渲染也失败时退回 LaTeX 原文（不静默丢失内容）。"""
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    latex = "\\brokenmacro"
    res = await _save_doc(client, practice, q, _formula_doc(latex))
    assert res.status_code == 200, res.text

    monkeypatch.setattr(docx_export, "_latex_to_omml", lambda tex, display: None)
    monkeypatch.setattr(docx_export._FormulaFallback, "render",
                        lambda self, tex, display: None)

    p = await _load_with_blocks(test_db, practice["id"])
    data, degraded = docx_export.build_docx(p, practice["id"])
    assert degraded == []
    assert f"${latex}$" in Document(io.BytesIO(data)).element.xml or \
           latex in "".join(para.text for para in Document(io.BytesIO(data)).paragraphs)


def test_formula_fallback_real_katex_render():
    """真实渲染：KaTeX + Playwright 把公式截图为 PNG（本地环境已装 chromium）。"""
    fb = docx_export._FormulaFallback()
    try:
        png = fb.render("\\frac{m}{V}", False)
        assert png and png.startswith(b"\x89PNG")
        assert fb.render("\\frac{m}{V}", False) is png   # 缓存命中（同对象）
        assert fb.render("\\badmacro{", False) is None    # KaTeX 语法错误 → None
    finally:
        fb.close()
