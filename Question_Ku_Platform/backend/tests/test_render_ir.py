"""统一渲染适配层（F07 Task 7.8）回归测试。

锁定三条被集中到 `render_ir` 的结构约定，防止 PDF/Word 再次各自推断结构：
1. `**…**` 归一为 bold mark（此前 HTML 转 `<b>`、Word 直接删星号，行为不一致）；
2. 题号必须置顶且与首段同行（此前 Word 富文档路径把题号追加到末尾）；
3. HTML 与 Word 由同一份 IR 驱动，题号与题干同段。
"""

import io

from docx import Document

from app.services import docx_export, render_ir
from app.services.render_service import build_practice_html
from test_blocks_api import _create_practice
from test_render_service import _load_with_blocks


def _doc(*nodes):
    return {"type": "doc", "content": list(nodes)}


def test_bold_markdown_normalized_to_marks():
    """`**…**` → bold mark：两个渲染器从此看到同一份格式信息。"""
    doc = _doc({"type": "paragraph", "content": [{"type": "text", "text": "a**b**c"}]})
    blocks = render_ir.blocks_from_rich_doc(doc)
    runs = [r for r in blocks[0].runs if isinstance(r, render_ir.Text)]
    assert [(r.text, r.marks.bold) for r in runs] == [("a", False), ("b", True), ("c", False)]


def test_prefix_hoisted_to_top_when_no_paragraph():
    """纯图片题（文档内无段落）：题号置顶并独立成段。"""
    doc = _doc({"type": "image", "attrs": {"src": "asset://practice/a.png"}})
    blocks = render_ir.with_prefix(render_ir.blocks_from_rich_doc(doc), "7. ")
    assert isinstance(blocks[0], render_ir.Paragraph)
    assert blocks[0].runs[0].text == "7. "
    assert isinstance(blocks[1], render_ir.ImageBlock)


def test_asset_ref_becomes_inline_image_run():
    """题干中的 asset 引用归一为内联图 run（此前只有 Word/选项路径会内联）。"""
    doc = _doc({"type": "paragraph",
                "content": [{"type": "text", "text": "见图 ![图](asset://figures/f.webp)"}]})
    blocks = render_ir.blocks_from_rich_doc(doc)
    kinds = [type(r).__name__ for r in blocks[0].runs]
    assert "InlineImage" in kinds
    assert not any(isinstance(r, render_ir.Text) and "asset://" in r.text
                   for r in blocks[0].runs)


async def test_prefix_inline_in_both_renderers(client, test_db, tmp_path):
    """题号与首段同行：HTML 与 Word 一致，且没有孤立题号段。"""
    practice = await _create_practice(client, test_db, tmp_path, content="唯一题干文本")
    pid = practice["id"]
    await client.get(f"/api/practices/{pid}/detail")   # 懒物化 + 题号重排为 1
    p = await _load_with_blocks(test_db, pid)

    html = build_practice_html(p, pid)
    assert '<div class="q-text"><b>1. </b>唯一题干文本</div>' in html

    doc = Document(io.BytesIO(docx_export.build_docx(p, pid)[0]))
    texts = [t.text for t in doc.paragraphs]
    assert any(t.startswith("1. ") and "唯一题干文本" in t for t in texts)
    assert not any(t.strip() == "1." for t in texts)   # 题号不得单独成段
