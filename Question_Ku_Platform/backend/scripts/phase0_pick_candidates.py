"""阶段 0 Task 0.2：从题库挑选基线样本候选题（只读）。

按学科找：含公式、含图、选项含图、长文本、混合题型的候选题，
输出候选题 ID 清单到 reports/phase0_baseline_candidates.json。
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR.parent / "data" / "db.sqlite3"
OUT = BACKEND_DIR / "scripts" / "reports" / "phase0_baseline_candidates.json"

FORMULA_RE = re.compile(r"\$\$([^$]+?)\$\$|\\\[(.+?)\\\]|(?<![\d$])\$(?!\$)([^$\n]+?)\$(?!\$)|\\\((.+?)\\\)")
IMG_RE = re.compile(r"asset://[^\s\)\"]+|/api/practices/[^\s\)\"]+")


def feat(content, options):
    content = content or ""
    has_formula = bool(FORMULA_RE.search(content))
    has_img = bool(IMG_RE.search(content))
    n_img = len(IMG_RE.findall(content))
    opt_img = False
    if options:
        try:
            opt_img = any(IMG_RE.search(o.get("content") or "") for o in json.loads(options))
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    return has_formula, has_img, n_img, opt_img, len(content)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select id, subject, question_type, content, options, question_number "
        "from questions where is_deleted=0").fetchall()

    out = {}
    for subj in ("physics", "math", "chemistry", "english"):
        cand = {"formula": [], "multi_img": [], "option_img": [], "long_text": [],
                "single_img": [], "by_type": {}}
        for r in rows:
            if r["subject"] != subj:
                continue
            hf, hi, ni, oi, ln = feat(r["content"], r["options"])
            item = {"id": r["id"], "qn": r["question_number"], "type": r["question_type"],
                    "len": ln}
            cand["by_type"].setdefault(r["question_type"], []).append(r["id"])
            if hf:
                cand["formula"].append(item)
            if ni >= 2:
                cand["multi_img"].append(item)
            elif hi:
                cand["single_img"].append(item)
            if oi:
                cand["option_img"].append(item)
            if ln >= 300:
                cand["long_text"].append(item)
        cand["total"] = sum(len(v) for v in cand["by_type"].values())
        out[subj] = cand
        print(f"[{subj}] 总={cand['total']} 公式={len(cand['formula'])} "
              f"多图={len(cand['multi_img'])} 单图={len(cand['single_img'])} "
              f"选项图={len(cand['option_img'])} 长文本={len(cand['long_text'])}")
        print("  题型:", {k: len(v) for k, v in cand["by_type"].items()})

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {OUT}")


if __name__ == "__main__":
    main()
