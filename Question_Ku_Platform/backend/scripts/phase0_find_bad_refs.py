"""定位基线样本中的外部图片引用（只读）。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "db.sqlite3"
sys.stdout.reconfigure(encoding="utf-8")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

print("== 全部练习题目中含 /api/ocr-assets（题干或选项）==")
for r in c.execute(
        "select pq.id, pq.question_number, pq.content_snapshot, pq.options_snapshot, p.title "
        "from practice_questions pq join practices p on p.id=pq.practice_id"):
    content = r["content_snapshot"] or ""
    opts = r["options_snapshot"] or ""
    if "/api/ocr-assets" in content or "/api/ocr-assets" in opts:
        where = []
        if "/api/ocr-assets" in content:
            where.append("题干")
        if "/api/ocr-assets" in opts:
            where.append("选项")
        print(f"[{r['title']}] 题{r['question_number']}: {'+'.join(where)}")

print("\n== 题库中含 /api/ocr-assets 引用的题 ==")
for r in c.execute(
        "select id, subject, question_number, content from questions "
        "where content like '%/api/ocr-assets%' and is_deleted=0"):
    print(f"[{r['subject']}] 题{r['question_number']}: {(r['content'] or '')[:180]!r}")
