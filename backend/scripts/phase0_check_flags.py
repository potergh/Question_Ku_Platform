"""只读：检查练习列表的 is_baseline 标记。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "db.sqlite3"
sys.stdout.reconfigure(encoding="utf-8")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
for r in c.execute("select title, is_baseline from practices order by title"):
    print(f"[{'基线' if r[1] else '普通'}] {r[0]}")
