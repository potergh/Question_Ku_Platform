"""智能选题推荐接口测试：过滤/打分/难度平均分配/排除已用/推荐理由。"""

from app.models import (Practice, PracticeQuestion, PracticeSection, Question,
                        SelectionBasketItem, Source, Tag)
from sqlalchemy import insert
from sqlalchemy.orm import selectinload

from app.models import question_tags


async def _seed_question(db, subject="physics", grade="初三", difficulty=3,
                         question_type="single_choice", content="题干", tag_names=None):
    source = Source(filename="中考模拟卷.pdf", file_path="/tmp/s.pdf", file_type="pdf")
    db.add(source)
    await db.commit()
    await db.refresh(source)
    q = Question(source_id=source.id, source_question_id="Q", question_number=1,
                 subject=subject, grade=grade, difficulty=difficulty,
                 question_type=question_type, content=content)
    db.add(q)
    await db.commit()
    q = await db.get(Question, q.id, options=[selectinload(Question.tags)])
    if tag_names:
        for name in tag_names:
            t = Tag(name=name, subject=subject, category="knowledge")
            db.add(t)
            await db.commit()
            await db.refresh(t)
            await db.execute(insert(question_tags).values(question_id=q.id, tag_id=t.id))
        await db.commit()
    return q


async def test_recommend_basic_and_count(client, test_db):
    """基础：按学科/题型过滤，返回 count×2 条。"""
    async with test_db() as db:
        for i in range(6):
            await _seed_question(db, difficulty=3, question_type="single_choice",
                                 content=f"选择题题干{i}")
        for i in range(4):
            await _seed_question(db, difficulty=3, question_type="fill_blank",
                                 content=f"填空题题干{i}")
    res = await client.post("/api/recommend", json={
        "subject": "physics", "question_types": ["选择题"], "count": 3,
        "difficulty_bands": ["medium"],
    })
    body = res.json()
    assert res.status_code == 200
    assert len(body["items"]) == 6  # count×2
    assert all(i["question_type"] == "single_choice" for i in body["items"])


async def test_recommend_difficulty_balanced(client, test_db):
    """选两档难度时平均分配：easy / hard 各占一半。"""
    async with test_db() as db:
        for i in range(6):
            await _seed_question(db, difficulty=1, content=f"易{i}")
        for i in range(6):
            await _seed_question(db, difficulty=5, content=f"难{i}")
    res = await client.post("/api/recommend", json={
        "difficulty_bands": ["easy", "hard"], "count": 5,
    })
    items = res.json()["items"]
    assert len(items) == 10
    easy = [i for i in items if i["difficulty"] in (1, 2)]
    hard = [i for i in items if i["difficulty"] in (4, 5)]
    assert len(easy) == 5 and len(hard) == 5


async def test_recommend_exclude_used(client, test_db):
    """排除已用：选题池已有 + 已入练习的题不出现。"""
    async with test_db() as db:
        q1 = await _seed_question(db, difficulty=3, content="选题池已有题")
        q2 = await _seed_question(db, difficulty=3, content="已入练习题")
        q3 = await _seed_question(db, difficulty=3, content="空闲题")
        db.add(SelectionBasketItem(basket_id="b", question_id=q1.id, position=0))
        p = Practice(title="练习")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        sec = PracticeSection(practice_id=p.id, title="选择题", section_type="选择题", position=0)
        db.add(sec)
        await db.commit()
        await db.refresh(sec)
        db.add(PracticeQuestion(practice_id=p.id, section_id=sec.id,
                                source_question_id=q2.id, position=0))
        await db.commit()
    res = await client.post("/api/recommend", json={"count": 5, "difficulty_bands": ["medium"]})
    ids = [i["id"] for i in res.json()["items"]]
    assert q3.id in ids
    assert q1.id not in ids
    assert q2.id not in ids


async def test_recommend_tag_hit_and_reason(client, test_db):
    """标签命中优先排序 + 推荐理由含考点名。"""
    async with test_db() as db:
        tagged = await _seed_question(db, content="带标签题", tag_names=["摩擦力", "二力平衡"])
        await _seed_question(db, content="无标签题")
    from sqlalchemy import select as _sel
    async with test_db() as db:
        tag = (await db.execute(_sel(Tag).where(Tag.name == "摩擦力"))).scalars().first()
        assert tag is not None
        tag_id = tag.id
    res = await client.post("/api/recommend", json={"tag_ids": [tag_id], "count": 2})
    items = res.json()["items"]
    assert items and items[0]["id"] == tagged.id
    assert "摩擦力" in items[0]["reason"]
