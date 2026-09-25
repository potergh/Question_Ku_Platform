"""阶段 0 Task 0.2：校验基线样本数据库状态（只读）。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "db.sqlite3"

sys.stdout.reconfigure(encoding="utf-8")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
for r in c.execute("select title, migration_status, status from practices where title like '基线-%'"):
    print(r)
total = c.execute(
    "select count(*) from practice_questions pq join practices p on p.id=pq.practice_id "
    "where p.title like '基线-%'").fetchone()[0]
with_doc = c.execute(
    "select count(*) from practice_questions pq join practices p on p.id=pq.practice_id "
    "where p.title like '基线-%' and pq.rich_document is not null").fetchone()[0]
scored = c.execute(
    "select count(*) from practice_questions pq join practices p on p.id=pq.practice_id "
    "where p.title like '基线-%' and pq.score is not null").fetchone()[0]
new_page = c.execute(
    "select count(*) from practice_sections ps join practices p on p.id=ps.practice_id "
    "where p.title like '基线-%' and ps.start_on_new_page=1").fetchone()[0]
print(f"题目 {total}，新文档 {with_doc}/{total}，有分值 {scored}/{total}，分页小节 {new_page}")
