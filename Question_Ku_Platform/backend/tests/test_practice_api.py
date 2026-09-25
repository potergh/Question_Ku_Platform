"""API tests for practices."""

from app.models import Source, Question


async def seed_basket_question(test_db, tmp_path, question_type="single_choice"):
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True, exist_ok=True)
    (ocr_dir / "figures" / "f.webp").write_bytes(b"img")
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                     question_type=question_type, content="题 ![图](asset://figures/f.webp)")
        db.add(q)
        await db.commit()
        await db.refresh(q)
        return q.id


async def test_create_from_basket(client, test_db, tmp_path):
    q1 = await seed_basket_question(test_db, tmp_path)
    q2 = await seed_basket_question(test_db, tmp_path, question_type="fill_blank")
    await client.post("/api/basket/items", json={"question_ids": [q1, q2]})

    res = await client.post("/api/practices", json={
        "title": "浮力练习", "subject": "physics", "grade": "初三",
        "from_basket": True, "clear_basket": True,
    })
    assert res.status_code == 200
    practice = res.json()
    assert practice["question_count"] == 2
    assert [s["title"] for s in practice["sections"]] == ["选择题", "填空题"]
    # 快照内容已解析为 HTTP 资产 URL
    content = practice["sections"][0]["questions"][0]["content"]
    assert f"/api/practices/{practice['id']}/assets/" in content

    # 选题池已清空（决策 7）
    assert (await client.get("/api/basket")).json()["total"] == 0

    # 资产文件可访问，且路径穿越被拒（403 或 404 均可，取决于路径解码方式）
    asset_url = content[content.index("/api/practices"):].split(")")[0]
    assert (await client.get(asset_url)).content == b"img"
    bad = asset_url.rsplit("/", 1)[0] + "/..%2F..%2Fdb.sqlite3"
    res_bad = await client.get(bad)
    assert res_bad.status_code in (403, 404)
    assert res_bad.content != (await client.get(asset_url)).content


async def test_create_empty_basket_fails(client, test_db, tmp_path):
    res = await client.post("/api/practices", json={"title": "空练习"})
    assert res.status_code == 400


async def test_create_from_explicit_ids(client, test_db, tmp_path):
    q1 = await seed_basket_question(test_db, tmp_path)
    res = await client.post("/api/practices", json={
        "title": "指定题目", "from_basket": False, "question_ids": [q1],
    })
    assert res.status_code == 200
    assert res.json()["question_count"] == 1


async def test_list_update_delete(client, test_db, tmp_path):
    q1 = await seed_basket_question(test_db, tmp_path)
    await client.post("/api/basket/items", json={"question_ids": [q1]})
    res = await client.post("/api/practices", json={"title": "练习A"})
    pid = res.json()["id"]

    res = await client.get("/api/practices")
    assert res.json()["total"] == 1
    assert res.json()["practices"][0]["question_count"] == 1

    res = await client.put(f"/api/practices/{pid}", json={"title": "练习B"})
    assert res.json()["title"] == "练习B"

    res = await client.delete(f"/api/practices/{pid}")
    assert res.json()["ok"] is True
    assert not (tmp_path / "practices" / pid).exists()
    assert (await client.get("/api/practices")).json()["total"] == 0


async def test_delete_last_question_cleans_empty_subtitle(client, test_db, tmp_path):
    """删除某题型最后一题 → 整册布局中该空小节标题同步移除（不留占位）。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models import Practice, PracticeSection
    q1 = await seed_basket_question(test_db, tmp_path, question_type="single_choice")
    q2 = await seed_basket_question(test_db, tmp_path, question_type="comprehensive")
    await client.post("/api/basket/items", json={"question_ids": [q1, q2]})
    res = await client.post("/api/practices", json={"title": "删除空小节", "from_basket": True})
    pid = res.json()["id"]
    # 删除前：触发布局生成，应含「综合题」小节
    async with test_db() as db:
        secs = (await db.execute(
            select(PracticeSection).where(PracticeSection.practice_id == pid)
            .options(selectinload(PracticeSection.questions)))).scalars().all()
        comp = next(s for s in secs if s.title == "综合题")
        pq_id = comp.questions[0].id
        p = (await db.execute(
            select(Practice).where(Practice.id == pid)
            .options(selectinload(Practice.sections).selectinload(PracticeSection.questions))
        )).scalar_one()
        if not p.layout_document:
            from app.services.workbook_layout import ensure_layout
            await ensure_layout(db, p)
            await db.commit()
        assert any(b.get("type") == "subtitle" and b.get("title") == "综合题" for b in p.layout_document)
    res = await client.delete(f"/api/practices/{pid}/questions/{pq_id}")
    assert res.status_code == 200
    async with test_db() as db:
        p = (await db.execute(select(Practice).where(Practice.id == pid))).scalar_one()
        assert not any(b.get("type") == "subtitle" and b.get("title") == "综合题" for b in p.layout_document)
        assert any(b.get("type") == "subtitle" and b.get("title") == "选择题" for b in p.layout_document)
