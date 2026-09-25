"""API tests for practice-level settings (page_config / layout_config passthrough)."""

from test_blocks_api import _create_practice


async def test_update_page_config(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.put(f"/api/practices/{pid}",
                           json={"title": "新标题", "page_config": {"show_info_bar": True}})
    assert res.status_code == 200
    assert res.json()["page_config"] == {"show_info_bar": True}
    assert res.json()["title"] == "新标题"


async def test_layout_config_passthrough(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    detail = (await client.get(f"/api/practices/{pid}/detail")).json()
    q = detail["sections"][0]["questions"][0]
    assert "layout_config" in q  # 默认 None，字段存在即可（单题留白覆盖用）
