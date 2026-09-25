"""API tests for selection basket."""

from app.models import Source, Question


async def seed_question(test_db, question_type="single_choice", content="测试题目", deleted=False):
    """造一道题，返回 question_id。"""
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf", ocr_status="done")
        db.add(source)
        await db.commit()
        q = Question(
            source_id=source.id, source_question_id="Q1", question_number=1,
            question_type=question_type, content=content, is_deleted=deleted,
        )
        db.add(q)
        await db.commit()
        await db.refresh(q)
        return q.id


async def test_basket_add_list_dedupe(client, test_db):
    q1 = await seed_question(test_db)
    q2 = await seed_question(test_db, question_type="fill_blank")

    res = await client.post("/api/basket/items", json={"question_ids": [q1, q2, q1]})
    assert res.status_code == 200
    assert res.json()["added"] == 2

    res = await client.get("/api/basket")
    data = res.json()
    assert data["total"] == 2
    assert data["type_stats"] == {"选择题": 1, "填空题": 1}
    assert [it["question"]["id"] for it in data["items"]] == [q1, q2]


async def test_basket_skip_deleted(client, test_db):
    qd = await seed_question(test_db, deleted=True)
    res = await client.post("/api/basket/items", json={"question_ids": [qd]})
    assert res.json()["added"] == 0


async def test_basket_remove_and_clear(client, test_db):
    q1 = await seed_question(test_db)
    q2 = await seed_question(test_db)
    await client.post("/api/basket/items", json={"question_ids": [q1, q2]})

    res = await client.post("/api/basket/items/remove", json={"question_ids": [q1]})
    assert res.json()["removed"] == 1

    res = await client.delete("/api/basket")
    assert res.json()["removed"] == 1
    assert (await client.get("/api/basket")).json()["total"] == 0


async def test_basket_reorder(client, test_db):
    q1 = await seed_question(test_db)
    q2 = await seed_question(test_db)
    await client.post("/api/basket/items", json={"question_ids": [q1, q2]})

    await client.put("/api/basket/reorder", json={"question_ids": [q2, q1]})
    res = await client.get("/api/basket")
    assert [it["question"]["id"] for it in res.json()["items"]] == [q2, q1]
