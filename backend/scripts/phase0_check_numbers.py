"""只读：全部练习的题号连续性检查。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "db.sqlite3"
sys.stdout.reconfigure(encoding="utf-8")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

for p in c.execute("select id, title from practices order by title"):
    nums = [r["question_number"] for r in c.execute(
        "select pq.question_number from practice_questions pq "
        "join practice_sections ps on ps.id=pq.section_id "
        "where pq.practice_id=? order by ps.position, pq.position", (p["id"],))]
    seq_ok = nums == list(range(1, len(nums) + 1))
    print(f"[{'OK' if seq_ok else '非连续'}] {p['title']}（{len(nums)} 题）: {nums}")
