"""阶段 1：单题富文本文档保存链路测试（编辑器为新真源，反推旧块/快照）。"""

from test_blocks_api import _create_practice, _question


async def test_detail_exposes_rich_document(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    doc = q["rich_document"]
    assert doc and doc["type"] == "doc" and doc["schema_version"] == 1
    types = [n["type"] for n in doc["content"]]
    # 与物化块一一对应：段落/图/段落/选项组/留白
    assert types == ["paragraph", "image", "paragraph", "optionGroup", "answerSpace"]


async def test_save_document_reverse_writes(client, test_db, tmp_path):
    """保存带 marks 的文档：旧块/快照被反推重建，marks 只保留在 rich_document。"""
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]

    doc = {
        "type": "doc", "schema_version": 1,
        "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "加粗题干", "marks": [{"type": "bold"}]}]},
            {"type": "optionGroup", "content": [
                {"type": "option", "attrs": {"label": "A"},
                 "content": [{"type": "text", "text": "甲"}]},
                {"type": "option", "attrs": {"label": "B"},
                 "content": [{"type": "text", "text": "乙"}]},
                {"type": "option", "attrs": {"label": "C"},
                 "content": [{"type": "text", "text": "丙"}]},
            ]},
            {"type": "answerSpace", "attrs": {"rows": 2}},
        ],
    }
    res = await client.put(f"/api/practices/{pid}/questions/{qid}/document",
                           json={"document": doc})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["question"]["is_modified"] is True
    # 旧块反推：文字 + 选项 + 留白
    assert [b["block_type"] for b in out["blocks"]] == ["text", "options", "answer_space"]
    assert out["blocks"][0]["content"] == "加粗题干"  # 旧块不含 marks
    assert len(out["blocks"][1]["content"]) == 3      # 选项数更新为 3
    assert out["blocks"][2]["style"] == {"rows": 2}
    # rich_document 保留编辑器原文（含 marks）
    saved = out["question"]["rich_document"]
    assert saved["content"][0]["content"][0]["marks"] == [{"type": "bold"}]
    # 快照同步
    detail = (await client.get(f"/api/practices/{pid}")).json()
    qq = detail["sections"][0]["questions"][0]
    assert qq["content"] == "加粗题干"
    assert [o["label"] for o in qq["options"]] == ["A", "B", "C"]


async def test_save_document_roundtrip_idempotent(client, test_db, tmp_path):
    """连续两次保存同一文档，文档/块/快照不再变化（双保存稳定性）。
    注：首次保存会把旧快照里行内图包装规范为独立图块，属预期规范化。"""
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]

    res = await client.put(f"/api/practices/{pid}/questions/{qid}/document",
                           json={"document": q["rich_document"]})
    assert res.status_code == 200, res.text
    res2 = await client.put(f"/api/practices/{pid}/questions/{qid}/document",
                            json={"document": q["rich_document"]})
    q2 = res2.json()["question"]
    q1 = res.json()["question"]
    assert q2["rich_document"] == q1["rich_document"]
    assert q2["content"] == q1["content"]
    assert [o for o in q2["options"]] == [o for o in q1["options"]]


async def test_save_document_inline_image_formula(client, test_db, tmp_path):
    """行内图/公式回到旧 Markdown 规范；块级图保留样式。"""
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]

    doc = {"type": "doc", "schema_version": 1, "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "质量为"},
            {"type": "inlineFormula", "attrs": {"latex": "m"}},
            {"type": "text", "text": "，如图"},
            {"type": "inlineImage", "attrs": {"src": "asset://figures/f.webp"}},
        ]},
        {"type": "image", "attrs": {"src": "asset://figures/f.webp",
                                     "align": "center", "width": "fit"}},
    ]}
    res = await client.put(f"/api/practices/{pid}/questions/{qid}/document",
                           json={"document": doc})
    out = res.json()
    types = [b["block_type"] for b in out["blocks"]]
    assert types == ["text", "image"]
    assert out["blocks"][0]["content"] == "质量为$m$，如图![图](asset://figures/f.webp)"
    assert out["blocks"][1]["style"] == {"align": "center", "width": "fit"}


async def test_save_document_rejects_invalid(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]

    bad_docs = [
        {"type": "doc", "schema_version": 99, "content": []},
        {"type": "paragraph", "content": []},
        {"type": "doc", "schema_version": 1, "content": [{"type": "script"}]},
        {"type": "doc", "schema_version": 1, "content": [
            {"type": "paragraph", "content": [{"type": "onclick"}]}]},
        {"type": "doc", "schema_version": 1, "content": [
            {"type": "answerSpace", "attrs": {"rows": -1}}]},
    ]
    for doc in bad_docs:
        res = await client.put(f"/api/practices/{pid}/questions/{qid}/document",
                               json={"document": doc})
        assert res.status_code == 422, doc
