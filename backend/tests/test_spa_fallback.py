"""阶段 0 Task 0.8：SPA history 路由回退回归测试。

覆盖：子页面直接访问/刷新、根路径、静态资源、未知 /api 路径不误吞、路径穿越防护。
"""

import pytest


@pytest.fixture
def fake_dist(tmp_path, monkeypatch):
    """临时前端构建产物：dist/index.html + dist/assets/app.js"""
    from app.config import settings

    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>spa-entry</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('js');", encoding="utf-8")
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    return dist


SUB_ROUTES = ["/", "/upload", "/library", "/basket", "/practices",
              "/practice/editor", "/tags", "/ai", "/settings"]


@pytest.mark.parametrize("path", SUB_ROUTES)
async def test_spa_subroutes_return_entry(client, fake_dist, path):
    """所有前端子路由直接访问均返回入口 HTML（刷新不 404）。"""
    resp = await client.get(path)
    assert resp.status_code == 200, path
    assert "spa-entry" in resp.text
    assert resp.headers["content-type"].startswith("text/html")


async def test_spa_unknown_frontend_path_returns_entry(client, fake_dist):
    """未定义的前端路径也回退到入口，由前端显示 404。"""
    resp = await client.get("/no/such/page")
    assert resp.status_code == 200
    assert "spa-entry" in resp.text


async def test_static_asset_served(client, fake_dist):
    """dist 内的静态资源原样返回，不回退为 HTML。"""
    resp = await client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text
    assert "spa-entry" not in resp.text


async def test_unknown_api_path_not_swallowed(client, fake_dist):
    """未知 /api 路径必须 404，不得回退为前端 HTML。"""
    resp = await client.get("/api/no-such-endpoint")
    assert resp.status_code == 404
    assert "spa-entry" not in resp.text


async def test_registered_api_still_works(client, fake_dist):
    """已注册 API 路由不受回退路由影响。"""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_path_traversal_blocked(client, fake_dist, tmp_path):
    """dist 外的文件不得被读取。"""
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")
    resp = await client.get("/%2e%2e/secret.txt")
    # 回退到 index.html 或 404 均可，但绝不能泄露文件内容
    assert "top-secret" not in resp.text


async def test_no_dist_returns_404(client, tmp_path, monkeypatch):
    """前端未构建时返回 404 而非 500。"""
    from app.config import settings

    monkeypatch.setattr(settings, "base_dir", tmp_path)
    resp = await client.get("/practice/editor")
    assert resp.status_code == 404
