"""一次性排查：MinerU 和平卷那 1 处确定性边界校验，为什么没拦住 Q21(2)->Q22 错位。

只读 data/ocr_output/*/extract.json，不改任何数据。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(r"D:\tiku_9.10\Question_Ku_Platform\data\ocr_output")
DOC = "2022年天津市和平区中考物理一模试卷__mineru"

data = json.loads((ROOT / DOC / "extract.json").read_text(encoding="utf-8"))
print("channel:", data.get("channel"))
print("全局 warnings 中与边界校验相关的:")
for w in data.get("warnings", []):
    if "边界" in w or "校验" in w:
        print("  -", w)

print()
print("含『确定性边界校验』warning 的题:")
for it in data.get("items", []):
    hits = [w for w in (it.get("warnings") or []) if "边界" in w]
    if not hits:
        continue
    print(f"  qid={it.get('qid')} label={it.get('label')!r} "
          f"number={it.get('question_number')} needs_review={it.get('needs_review')} "
          f"flags={it.get('audit_flags')}")
    for h in hits:
        print("     ·", h)

print()
print("Q21 / Q22 两题的完整状态:")
for it in data.get("items", []):
    label = str(it.get("label") or "")
    if "21" in label or "22" in label or it.get("question_number") in (21, 22):
        print(f"  qid={it.get('qid')} label={label!r} number={it.get('question_number')} "
              f"needs_review={it.get('needs_review')} flags={it.get('audit_flags')}")
        print(f"     answer={str(it.get('answer'))[:60]!r}")
        print(f"     stem 前两行: {(it.get('stem_md') or '')[:80]!r}")
        print(f"     warnings: {it.get('warnings')}")
        print()
