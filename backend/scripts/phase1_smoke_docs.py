"""阶段 1 冒烟：校验库里全部题目的 rich_document 符合 schema v1 且可反推为旧块。

只读脚本，不修改数据。用法：
    python scripts/phase1_smoke_docs.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.practice import PracticeQuestion  # noqa: E402
from app.services.rich_document import blocks_from_doc, validate_doc  # noqa: E402


async def main():
    async with async_session_factory() as db:
        rows = (await db.execute(
            select(PracticeQuestion.id, PracticeQuestion.rich_document,
                   PracticeQuestion.question_number)
        )).all()

    total = len(rows)
    missing = bad = 0
    for r in rows:
        if not r.rich_document:
            missing += 1
            print(f"[缺文档] pq={r.id}（题号{r.question_number}）")
            continue
        try:
            doc = json.loads(r.rich_document)
        except (TypeError, ValueError):
            bad += 1
            print(f"[JSON坏] pq={r.id}")
            continue
        errors = validate_doc(doc)
        if errors:
            bad += 1
            print(f"[校验失败] pq={r.id}: {'；'.join(errors[:3])}")
            continue
        blocks_from_doc(doc)   # 反推不抛异常即可

    print(f"共 {total} 题：缺文档 {missing}，非法 {bad}，合法 {total - missing - bad}")
    if missing or bad:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
