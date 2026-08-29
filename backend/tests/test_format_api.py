"""API tests for one-click formatting (regroup + unify layout)."""

from test_blocks_api import _create_practice
from test_structure_api import _two_questions


async def test_regroup(client, test_db, tmp_path):
    practice = await _two_questions(client, test_db, tmp_path)
    pid = practice["id"]
    fill = practice["sections"][1]
    choice = practice["sections"][0]
    q_choice = choice["questions"][0]
    # 打乱：先造自定义小节，再把选择题移入填空小节（题型错序）
    await client.post(f"/api/practices/{pid}/sections", json={"title": "附加题"})
    await client.put(f"/api/practices/{pid}/questions/{q_choice['id']}/move",
                     json={"target_section_id": fill["id"]})

    res = await client.post(f"/api/practices/{pid}/regroup/preview")
    assert res.json()["applies"] is True and res.json()["changes"]

    res = await client.post(f"/api/practices/{pid}/regroup/apply")
    secs = res.json()["sections"]
    assert secs[0]["section_type"] == "选择题"
    assert secs[-1]["section_type"] == "custom"  # 自定义小节置底且保留（空题）
    numbers = [q["question_number"] for s in secs for q in s["questions"]]
    assert numbers == sorted(numbers)


async def test_unify_layout(client, test_db, tmp_path):
    practice = await _create_practice(client, test_db, tmp_path,
                                      question_type="fill_blank",
                                      options=None)
    pid = practice["id"]
    q = (await client.get(f"/api/practices/{pid}/detail")).json() \
        ["sections"][0]["questions"][0]
    # 定制留白 → 统一排版不得覆盖（规格 9.3）
    space = next(b for b in q["blocks"] if b["block_type"] == "answer_space")
    await client.put(f"/api/practices/{pid}/questions/{q['id']}/blocks/{space['id']}",
                     json={"style": {"rows": 12}})
    # 把图片样式清空（模拟未定制）→ 统一排版应补上默认样式，验证 unify 真实生效
    img = next(b for b in q["blocks"] if b["block_type"] == "image")
    await client.put(f"/api/practices/{pid}/questions/{q['id']}/blocks/{img['id']}",
                     json={"style": None})

    res = await client.post(f"/api/practices/{pid}/layout/unify")
    assert res.status_code == 200 and res.json()["adjusted"] >= 1

    q = (await client.get(f"/api/practices/{pid}/detail")).json() \
        ["sections"][0]["questions"][0]
    space = next(b for b in q["blocks"] if b["block_type"] == "answer_space")
    assert space["style"]["rows"] == 12          # 定制保留
    img = next(b for b in q["blocks"] if b["block_type"] == "image")
    assert img["style"] == {"align": "center", "width": "fit"}  # 未定制图片被统一
