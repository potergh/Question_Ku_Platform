"""预览/导出管线 API 测试：真实启动 chromium（单用例约 2-4 秒）。"""

from test_blocks_api import _create_practice


async def test_render_and_pages_image(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.post(f"/api/practices/{pid}/render")
    assert res.status_code == 200
    data = res.json()
    assert data["pages"] >= 1 and len(data["sha"]) == 40

    img = await client.get(f"/api/practices/{pid}/preview/page/1")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content.startswith(b"\x89PNG")

    bad = await client.get(f"/api/practices/{pid}/preview/page/999")
    assert bad.status_code == 404


async def test_render_refreshes_after_edit(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    sha1 = (await client.post(f"/api/practices/{pid}/render")).json()["sha"]
    # 改第一个文字块 → HTML 变化 → sha 变化
    detail = (await client.get(f"/api/practices/{pid}/detail")).json()
    q = detail["sections"][0]["questions"][0]
    bid = next(b["id"] for b in q["blocks"] if b["block_type"] == "text")
    await client.put(f"/api/practices/{pid}/questions/{q['id']}/blocks/{bid}",
                     json={"content": "预览缓存验证"})
    sha2 = (await client.post(f"/api/practices/{pid}/render")).json()["sha"]
    assert sha1 != sha2
    assert (await client.get(f"/api/practices/{pid}/preview/page/1")).status_code == 200


async def test_page_requires_render(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    res = await client.get(f"/api/practices/{practice['id']}/preview/page/1")
    assert res.status_code == 404   # 未先 POST render


async def test_export_pdf(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.get(f"/api/practices/{pid}/export/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")
    assert "filename" in res.headers.get("content-disposition", "")
