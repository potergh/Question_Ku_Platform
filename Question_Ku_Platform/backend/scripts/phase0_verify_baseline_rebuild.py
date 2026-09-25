"""复验：基线重建后题号连续、无坏引用（只读）。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "db.sqlite3"
sys.stdout.reconfigure(encoding="utf-8")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

ok = True
for p in c.execute("select id, title from practices where title like '基线-%' order by title"):
    nums = [r["question_number"] for r in c.execute(
        "select pq.question_number from practice_questions pq "
        "join practice_sections ps on ps.id=pq.section_id "
        "where pq.practice_id=? order by ps.position, pq.position", (p["id"],))]
    expect = list(range(1, len(nums) + 1))
    seq_ok = nums == expect
    ok &= seq_ok
    bad = c.execute(
        "select count(*) as n from practice_questions "
        "where practice_id=? and (content_snapshot like '%/api/ocr-assets%' "
        "or options_snapshot like '%/api/ocr-assets%' or rich_document like '%/api/ocr-assets%')",
        (p["id"],)).fetchone()["n"]
    ok &= bad == 0
    print(f"[{'OK' if seq_ok else 'FAIL'}] {p['title']}：题号 {nums[:6]}{'…' if len(nums) > 6 else ''}"
          f"（{len(nums)} 题），坏引用 {bad} 处")
print("结论:", "全部连续且无坏引用" if ok else "存在问题")
