"""Word 导出：构建结果用 python-docx 回读断言。"""

import io

from docx import Document

from test_blocks_api import _create_practice


async def _build(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    res = await client.get(f"/api/practices/{practice['id']}/export/docx")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return practice, Document(io.BytesIO(res.content))


async def test_docx_structure(client, test_db, tmp_path):
    practice, doc = await _build(client, test_db, tmp_path)
    texts = [p.text for p in doc.paragraphs]
    assert any(practice["title"] in t for t in texts)          # 标题
    assert any("姓名" in t for t in texts)                      # 默认学生信息栏
    assert any(t.startswith("1.") for t in texts)               # 题号
    assert any("A." in t for t in texts)                        # 选项（单选题）
    # fixture 题带一张 .webp 图（块序 text/image/text/options/answer_space）
    assert len(doc.inline_shapes) >= 1


async def test_docx_export_marks_status(client, test_db, tmp_path):
    practice, _ = await _build(client, test_db, tmp_path)
    item = (await client.get("/api/practices")).json()
    mine = next(p for p in item["practices"] if p["id"] == practice["id"])
    assert mine["status"] == "exported"
