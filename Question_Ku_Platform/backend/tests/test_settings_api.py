"""设置接口的密钥语义锁。

`ai_api_key` 与 `mineru_api_token` 都是「留空 = 保留原值」：前端不持有明文，
无法把原值回传，所以 PUT 时空值若被当成清空，用户每次改别的字段都会顺手
把 Key 抹掉 —— 而且不会报错，只会在下次识别时才发现。

这条语义以前只存在于 ai_api_key 上且没有测试；加 MinerU Token 时它被复制
到了第二个字段，因此必须锁住：再复制一次就该由测试而不是用户来发现。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.settings import Settings

KEY = "sk-abcdefghijklmn"
TOKEN = "sk-mineru-token-123456"


async def _row(test_db) -> Settings:
    async with test_db() as db:
        return (await db.execute(select(Settings).where(Settings.id == 1))).scalar_one()


async def test_masks_secrets_and_keeps_them_on_partial_update(client, test_db):
    resp = await client.put(
        "/api/settings",
        json={"ai_mode": "remote", "ai_api_key": KEY, "mineru_api_token": TOKEN},
    )
    assert resp.status_code == 200
    body = resp.json()
    # 只回打码值，明文绝不出现在响应里
    assert body["ai_api_key_masked"] == "sk-a****klmn"
    assert body["mineru_api_token_masked"] == "sk-m****3456"
    assert KEY not in resp.text
    assert TOKEN not in resp.text

    # 只改别的字段：两个密钥都必须保留
    resp = await client.put("/api/settings", json={"ai_model": "qwen-max"})
    assert resp.status_code == 200
    assert resp.json()["ai_model"] == "qwen-max"
    assert resp.json()["mineru_api_token_masked"] == "sk-m****3456"
    row = await _row(test_db)
    assert row.ai_api_key == KEY
    assert row.mineru_api_token == TOKEN

    # 显式传空串 = 保留原值（与「不传」同义）
    resp = await client.put(
        "/api/settings", json={"ai_api_key": "", "mineru_api_token": ""}
    )
    assert resp.status_code == 200
    row = await _row(test_db)
    assert row.ai_api_key == KEY
    assert row.mineru_api_token == TOKEN


async def test_get_settings_exposes_mineru_field(client, test_db):
    """GET 必须带上 MinerU 字段，否则设置页读不回已保存的 Token（会显示成空）。"""
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    assert "mineru_api_token_masked" in resp.json()


async def test_mineru_params_roundtrip(client, test_db):
    """MinerU 解析参数不是密钥，改完必须能读回来并落库。

    读不回来时的症状最难查：界面显示默认值、识别也用默认值，
    用户以为自己改过了。
    """
    payload = {
        "mineru_model_version": "pipeline",
        "mineru_language": "ch_server",
        "mineru_enable_formula": False,
        "mineru_enable_table": False,
    }
    resp = await client.put("/api/settings", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    for key, value in payload.items():
        assert body[key] == value, f"{key} 未回显"

    row = await _row(test_db)
    assert row.mineru_model_version == "pipeline"
    assert row.mineru_language == "ch_server"
    assert row.mineru_enable_formula is False
    assert row.mineru_enable_table is False

    fresh = await client.get("/api/settings")
    assert fresh.json()["mineru_model_version"] == "pipeline"
