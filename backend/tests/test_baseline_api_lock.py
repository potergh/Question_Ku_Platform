"""阶段 0 Task 0.3：固定当前 API 行为的基线回归测试。

补齐既有测试未覆盖的行为锁定：小节排序、小节更新、题目元数据更新、
列表/详情响应形状、详情幂等（重复打开不重复物化块）。
这些行为在编辑器重构期间不得回归。
"""

from test_blocks_api import _create_practice
from test_structure_api import _two_questions


async def test_list_and_detail_response_shape(client, test_db, tmp_path):
    """列表与详情响应字段固定，前端依赖这些字段。"""
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]

    lst = (await client.get("/api/practices")).json()
    assert lst["total"] >= 1
    brief = next(p for p in lst["practices"] if p["id"] == pid)
    for key in ("id", "title", "subtitle", "subject", "grade", "status",
                "question_count", "is_baseline", "created_at"):
        assert key in brief

    detail = (await client.get(f"/api/practices/{pid}")).json()
    for key in ("id", "title", "subtitle", "subject", "grade", "status",
                "question_count", "is_baseline", "page_config", "sections"):
        assert key in detail
    q = detail["sections"][0]["questions"][0]
    for key in ("id", "position", "question_number", "question_type",
                "content", "options", "is_modified", "layout_config", "blocks"):
        assert key in q

    res = await client.get("/api/practices/no-such-id")
    assert res.status_code == 404


async def test_detail_idempotent(client, test_db, tmp_path):
    """重复打开详情不得重复物化内容块（幂等基线）。"""
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    d1 = (await client.get(f"/api/practices/{pid}/detail")).json()
    d2 = (await client.get(f"/api/practices/{pid}/detail")).json()
    q1 = d1["sections"][0]["questions"][0]
    q2 = d2["sections"][0]["questions"][0]
    assert len(q1["blocks"]) == len(q2["blocks"])
    assert [b["id"] for b in q1["blocks"]] == [b["id"] for b in q2["blocks"]]


async def test_reorder_sections(client, test_db, tmp_path):
    """小节排序：倒序提交后位置生效；题号在下次打开详情时幂等重排。"""
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    sids = [s["id"] for s in practice["sections"]]
    res = await client.put(f"/api/practices/{pid}/sections/reorder",
                           json={"section_ids": list(reversed(sids))})
    assert res.status_code == 200
    new_order = [s["id"] for s in res.json()["sections"]]
    assert new_order == list(reversed(sids))
    # 当前行为锁定：排序接口不立即重排题号，详情接口幂等重排（填空在前 → 题号 1、2）
    detail = (await client.get(f"/api/practices/{pid}/detail")).json()
    nums = [q["question_number"] for s in detail["sections"] for q in s["questions"]]
    assert nums == [1, 2]
    assert detail["sections"][0]["section_type"] == "填空题"


async def test_update_section(client, test_db, tmp_path):
    """小节更新：标题、隐藏标题、从新页开始。"""
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    sec = practice["sections"][0]
    res = await client.put(f"/api/practices/{pid}/sections/{sec['id']}",
                           json={"title": "一、选择题（改）", "show_title": False,
                                 "start_on_new_page": True})
    assert res.status_code == 200
    updated = next(s for s in res.json()["sections"] if s["id"] == sec["id"])
    assert updated["title"] == "一、选择题（改）"
    assert updated["show_title"] is False
    assert updated["start_on_new_page"] is True
    # 部分更新：只改标题不重置其他字段
    res = await client.put(f"/api/practices/{pid}/sections/{sec['id']}",
                           json={"title": "选择题"})
    updated = next(s for s in res.json()["sections"] if s["id"] == sec["id"])
    assert updated["title"] == "选择题"
    assert updated["show_title"] is False  # 未被部分更新重置


async def test_update_question_meta(client, test_db, tmp_path):
    """题目元数据更新：题型/难度/分值，且计入已修改状态。"""
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    detail = (await client.get(f"/api/practices/{pid}/detail")).json()
    q = detail["sections"][0]["questions"][0]
    assert q["is_modified"] is False

    res = await client.put(f"/api/practices/{pid}/questions/{q['id']}",
                           json={"difficulty": 3, "score": 5.0})
    assert res.status_code == 200
    q2 = res.json()["sections"][0]["questions"][0]
    assert q2["difficulty"] == 3
    assert q2["score"] == 5.0
    assert q2["is_modified"] is True  # 元数据修改也计入已修改


async def test_update_practice_fields(client, test_db, tmp_path):
    """练习级更新：标题、副标题、学科、年级。"""
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.put(f"/api/practices/{pid}", json={
        "title": "基线练习", "subtitle": "阶段 0", "subject": "物理", "grade": "初三"})
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "基线练习"
    assert data["subtitle"] == "阶段 0"
    assert data["subject"] == "物理"
    assert data["grade"] == "初三"


async def test_is_baseline_flag(client, test_db, tmp_path):
    """基线标记：新建默认 False，置位后列表/详情均可见（用户决策 2026-08-30：标记不隐藏）。"""
    from sqlalchemy import select
    from app.models.practice import Practice
    practice = await _create_practice(client, test_db, tmp_path)
    pid = practice["id"]
    brief = next(p for p in (await client.get("/api/practices")).json()["practices"]
                 if p["id"] == pid)
    assert brief["is_baseline"] is False
    async with test_db() as db:
        p = (await db.execute(select(Practice).where(Practice.id == pid))).scalar_one()
        p.is_baseline = True
        await db.commit()
    brief = next(p for p in (await client.get("/api/practices")).json()["practices"]
                 if p["id"] == pid)
    assert brief["is_baseline"] is True
    assert (await client.get(f"/api/practices/{pid}")).json()["is_baseline"] is True
