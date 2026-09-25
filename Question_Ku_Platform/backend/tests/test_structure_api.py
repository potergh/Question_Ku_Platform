"""API tests for practice structure editing."""

from sqlalchemy import select

from app.models import Source, Question

from test_blocks_api import _create_practice  # noqa: F401  供其他测试模块复用


async def _two_questions(client, test_db, tmp_path):
    """造含两题（选择题 + 填空题）的练习。"""
    ocr_dir = tmp_path / "ocr" / "d"
    (ocr_dir / "figures").mkdir(parents=True, exist_ok=True)
    async with test_db() as db:
        source = Source(filename="t.pdf", file_path="/tmp/t.pdf", file_type="pdf",
                        ocr_status="done", ocr_result_path=str(ocr_dir))
        db.add(source)
        await db.commit()
        q1 = Question(source_id=source.id, source_question_id="Q1", question_number=1,
                      question_type="single_choice", content="选择题题干",
                      options=[{"label": "A", "content": "x"}])
        q2 = Question(source_id=source.id, source_question_id="Q2", question_number=2,
                      question_type="fill_blank", content="填空题题干")
        db.add_all([q1, q2])
        await db.commit()
        await db.refresh(q1)
        await db.refresh(q2)
        ids = [q1.id, q2.id]
    res = await client.post("/api/practices", json={
        "title": "t", "from_basket": False, "question_ids": ids})
    return res.json()


async def test_add_and_delete_section(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    res = await client.post(f"/api/practices/{pid}/sections", json={"title": "附加题"})
    assert res.status_code == 200
    new_sec = res.json()["sections"][-1]
    assert new_sec["title"] == "附加题" and new_sec["section_type"] == "custom"
    # 空小节可删，有题目的小节不可删
    res = await client.delete(f"/api/practices/{pid}/sections/{new_sec['id']}")
    assert res.status_code == 200
    busy = res.json()["sections"][0]
    res = await client.delete(f"/api/practices/{pid}/sections/{busy['id']}")
    assert res.status_code == 400


async def test_add_questions_from_library(client, test_db, tmp_path):
    """已有练习继续从题库添加：按题型归入小节（缺则新建），已在练习内的跳过，全练习连续编号。"""
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    dup_id = practice["sections"][0]["questions"][0]["source_question_id"]   # 已在练习内，应跳过
    async with test_db() as db:
        source = (await db.execute(select(Source))).scalars().first()
        q3 = Question(source_id=source.id, source_question_id="Q3", question_number=7,
                      question_type="calculation", content="计算题题干")
        db.add(q3)
        await db.commit()
        await db.refresh(q3)
        q3_id = q3.id

    res = await client.post(f"/api/practices/{pid}/questions/add",
                            json={"question_ids": [q3_id, dup_id]})
    assert res.status_code == 200
    data = res.json()
    assert data["question_count"] == 3   # 重复题未重复加入
    nums = [q["question_number"] for s in data["sections"] for q in s["questions"]]
    assert nums == [1, 2, 3]   # 来源编号 7 重排为连续 3
    calc = next(s for s in data["sections"] if s["title"] == "计算题")
    assert len(calc["questions"]) == 1

    # 再添加同类型题目 → 归入已有计算题小节末尾，不新建重复小节
    async with test_db() as db:
        source = (await db.execute(select(Source))).scalars().first()
        q4 = Question(source_id=source.id, source_question_id="Q4", question_number=8,
                      question_type="calculation", content="计算题题干二")
        db.add(q4)
        await db.commit()
        await db.refresh(q4)
        q4_id = q4.id
    res = await client.post(f"/api/practices/{pid}/questions/add", json={"question_ids": [q4_id]})
    data = res.json()
    assert data["question_count"] == 4
    calc_secs = [s for s in data["sections"] if s["title"] == "计算题"]
    assert len(calc_secs) == 1 and len(calc_secs[0]["questions"]) == 2


async def test_move_question_and_renumber(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    sec_choice = practice["sections"][0]   # 选择题（题号1）
    sec_fill = practice["sections"][1]     # 填空题（题号2）
    q_choice = sec_choice["questions"][0]
    # 把选择题移到填空题小节末尾 → 编号变 2，填空变 1；目标小节保留原名（填空题）
    res = await client.put(f"/api/practices/{pid}/questions/{q_choice['id']}/move",
                           json={"target_section_id": sec_fill["id"]})
    data = res.json()
    fill_sec = next(s for s in data["sections"] if s["id"] == sec_fill["id"])
    nums = [q["question_number"] for q in fill_sec["questions"]]
    assert nums == [1, 2]
    assert fill_sec["questions"][1]["id"] == q_choice["id"]
    assert fill_sec["title"] == "填空题"  # 小节名不随移入题目改变；题型归位交给一键整理结构
    assert len(data["sections"]) == 1  # 空选择题小节被自动删除


async def test_delete_question(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    q1 = practice["sections"][0]["questions"][0]
    res = await client.delete(f"/api/practices/{pid}/questions/{q1['id']}")
    assert res.status_code == 200
    numbers = [q["question_number"] for s in res.json()["sections"] for q in s["questions"]]
    assert numbers == [1]  # 重新连续编号，空小节移除后只剩填空题（题号1）
