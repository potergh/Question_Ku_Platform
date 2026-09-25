"""API tests for has_answer / has_explanation filters."""

from app.models import Source, Question


async def seed(test_db, **fields):
    async with test_db() as db:
        source = Source(filename="f.pdf", file_path="/tmp/f.pdf", file_type="pdf")
        db.add(source)
        await db.commit()
        q = Question(source_id=source.id, source_question_id="Q", question_number=1,
                     content="c", **fields)
        db.add(q)
        await db.commit()
        await db.refresh(q)
        return q.id


async def test_has_answer_filter(client, test_db):
    await seed(test_db, answer="A")
    await seed(test_db, answer="")
    await seed(test_db)  # None

    assert (await client.get("/api/questions", params={"has_answer": "true"})).json()["total"] == 1
    assert (await client.get("/api/questions", params={"has_answer": "false"})).json()["total"] == 2


async def test_has_explanation_filter(client, test_db):
    await seed(test_db, explanation="因为所以")
    await seed(test_db)

    assert (await client.get("/api/questions", params={"has_explanation": "true"})).json()["total"] == 1
