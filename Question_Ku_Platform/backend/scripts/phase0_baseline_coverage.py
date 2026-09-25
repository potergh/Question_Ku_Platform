"""阶段 0 Task 0.2：基线样本特征盘点（只读）。

统计每份练习的学科、题型、公式/图片/选项图/留白分布、页数线索，
对照计划要求（物理主基线 + 数学/化学/英语代表 + 至少一份三页以上）。
输出：backend/scripts/reports/phase0_baseline_coverage.json
"""

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR.parent / "data" / "db.sqlite3"
REPORT_DIR = BACKEND_DIR / "scripts" / "reports"

FORMULA_RE = re.compile(r"\$\$([^$]+?)\$\$|\\\[(.+?)\\\]|(?<![\d$])\$(?!\$)([^$\n]+?)\$(?!\$)|\\\((.+?)\\\)")
IMG_RE = re.compile(r"asset://[^\s\)\"]+|/api/practices/[^\s\)\"]+")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    report = {"practices": []}

    for p in conn.execute("select * from practices order by created_at"):
        qrows = conn.execute(
            """select pq.*, ps.position as sec_pos from practice_questions pq
               join practice_sections ps on ps.id = pq.section_id
               where pq.practice_id = ? order by ps.position, pq.position""",
            (p["id"],)).fetchall()

        types = Counter()
        formula_q = image_q = opt_img_q = space_blocks = 0
        text_chars = 0
        for q in qrows:
            types[q["question_type"]] += 1
            content = q["content_snapshot"] or ""
            text_chars += len(content)
            if FORMULA_RE.search(content):
                formula_q += 1
            if IMG_RE.search(content):
                image_q += 1
            if q["options_snapshot"]:
                try:
                    opts = json.loads(q["options_snapshot"])
                    if any(IMG_RE.search(o.get("content") or "") for o in opts):
                        opt_img_q += 1
                except (json.JSONDecodeError, AttributeError):
                    pass
            space_blocks += conn.execute(
                "select count(*) from practice_content_blocks where practice_question_id=? and block_type='answer_space'",
                (q["id"],)).fetchone()[0]

        entry = {
            "id": p["id"], "title": p["title"],
            "subject": p["subject"], "grade": p["grade"],
            "subtitle": p["subtitle"], "page_config": p["page_config"],
            "questions": len(qrows), "types": dict(types),
            "formula_questions": formula_q, "image_questions": image_q,
            "option_image_questions": opt_img_q, "answer_space_blocks": space_blocks,
            "total_text_chars": text_chars,
            "migration_status": p["migration_status"],
        }
        report["practices"].append(entry)

    # 题库中可按学科选题的储备（用于补建缺失学科的基线）
    report["bank_by_subject"] = {
        r["subject"] or "(无)": r["n"] for r in conn.execute(
            "select subject, count(*) n from questions group by subject")}
    report["bank_types"] = {
        r["question_type"]: r["n"] for r in conn.execute(
            "select question_type, count(*) n from questions group by question_type")}

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "phase0_baseline_coverage.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for e in report["practices"]:
        print(f"[{e['subject'] or '?'}] {e['title']}：{e['questions']}题 题型={e['types']} "
              f"公式={e['formula_questions']} 图={e['image_questions']} 选项图={e['option_image_questions']} "
              f"留白块={e['answer_space_blocks']} 字数≈{e['total_text_chars']}")
    print("题库学科分布:", report["bank_by_subject"])
    print(f"报告: {out}")


if __name__ == "__main__":
    main()
