"""API tests for question content blocks."""

import io

from PIL import Image

from app.models import Source, Question

CONTENT = "题干A ![图](asset://figures/f.webp) 题干B"


def _tiny_webp() -> bytes:
    """1×1 真实 WebP：python-docx add_picture 需可读图片头取尺寸。"""
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "WEBP")
    return buf.getvalue()


async def _create_practice(client, test_db, tmp_path, content=CONTENT,
                           question_type="single_choice",
                           options=None):
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True, exist_ok=True)
    (ocr_dir / "figures" / "f.webp").write_bytes(_tiny_webp())
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                     question_type=question_type, content=content,
                     options=options if options is not None
                     else [{"label": "A", "content": "x"}])
        db.add(q)
        await db.commit()
        await db.refresh(q)
        qid = q.id
    res = await client.post("/api/practices", json={
        "title": "t", "from_basket": False, "question_ids": [qid]})
    return res.json()


async def _question(client, practice):
    detail = (await client.get(f"/api/practices/{practice['id']}/detail")).json()
    return detail["sections"][0]["questions"][0]


async def test_detail_materializes_blocks(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    types = [b["block_type"] for b in q["blocks"]]
    assert types == ["text", "image", "text", "options", "answer_space"]
    assert q["blocks"][1]["content"].startswith("/api/practices/")
    assert q["blocks"][3]["content"] == [{"label": "A", "content": "x"}]  # API 层已解析为数组


async def test_block_crud_and_rebuild(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]

    # 改文字块 → 快照重建
    res = await client.put(f"/api/practices/{pid}/questions/{qid}/blocks/{q['blocks'][0]['id']}",
                           json={"content": "改过的题干"})
    assert res.json()["question"]["is_modified"] is True
    detail = (await client.get(f"/api/practices/{pid}")).json()
    assert "改过的题干" in detail["sections"][0]["questions"][0]["content"]

    # 新增文字块
    res = await client.post(f"/api/practices/{pid}/questions/{qid}/blocks",
                            json={"block_type": "text", "content": "补充说明"})
    assert res.status_code == 200 and len(res.json()["blocks"]) == 6

    # 重排：把补充说明移到最前
    ids = [b["id"] for b in res.json()["blocks"]]
    ids.insert(0, ids.pop())
    res = await client.put(f"/api/practices/{pid}/questions/{qid}/blocks/reorder",
                           json={"block_ids": ids})
    assert res.json()["blocks"][0]["content"] == "补充说明"

    # 删除图片块
    img = next(b for b in res.json()["blocks"] if b["block_type"] == "image")
    res = await client.delete(f"/api/practices/{pid}/questions/{qid}/blocks/{img['id']}")
    assert all(b["block_type"] != "image" for b in res.json()["blocks"])


async def test_restore(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    q = await _question(client, practice)
    pid, qid = practice["id"], q["id"]
    await client.put(f"/api/practices/{pid}/questions/{qid}/blocks/{q['blocks'][0]['id']}",
                     json={"content": "改坏"})
    res = await client.post(f"/api/practices/{pid}/questions/{qid}/restore")
    assert res.status_code == 200
    assert res.json()["question"]["is_modified"] is False
    assert "题干A" in res.json()["question"]["content"]


async def test_assets_list(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    res = await client.get(f"/api/practices/{practice['id']}/assets-list")
    assert res.json()["assets"] and res.json()["assets"][0].endswith(".webp")
