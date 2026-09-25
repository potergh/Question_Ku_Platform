"""一次性修复：practice_questions.rich_document 里的空 text 节点。

ProseMirror 禁止 text.text 为空，tiptap 遇到会丢弃整份文档（整题空白）。
本脚本外科手术式地只删空 text 节点，其余内容一字不动；段落内容被删空时
保留为空段落（合法节点）。先备份 db.sqlite3 再动手。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path(r"D:\tiku_9.10\Question_Ku_Platform\data\db.sqlite3")

backup = DB.with_name(f"db_backup_richdoc_{datetime.now():%Y%m%d_%H%M%S}.sqlite3")
shutil.copy2(DB, backup)
print("已备份 ->", backup.name)


def clean(nodes):
    """递归删除空 text 节点；返回 (新列表, 是否有改动)。"""
    changed = False
    out = []
    for n in nodes or []:
        if not isinstance(n, dict):
            out.append(n)
            continue
        if n.get("type") == "text" and not (n.get("text") or ""):
            changed = True
            continue
        if isinstance(n.get("content"), list):
            kids, kid_changed = clean(n["content"])
            changed = changed or kid_changed
            n = {**n, "content": kids}
        out.append(n)
    return out, changed


conn = sqlite3.connect(DB)
rows = conn.execute(
    "select id, rich_document from practice_questions where rich_document is not null"
).fetchall()

fixed = 0
for pq_id, raw in rows:
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        continue
    content, changed = clean(doc.get("content") or [])
    if not changed:
        continue
    doc["content"] = [
        ({k: v for k, v in n.items() if k != "content"} if not n.get("content") else n)
        for n in content
    ]
    conn.execute(
        "update practice_questions set rich_document=? where id=?",
        (json.dumps(doc, ensure_ascii=False), pq_id),
    )
    fixed += 1

conn.commit()
conn.close()
print(f"修复题数: {fixed} / {len(rows)}")
