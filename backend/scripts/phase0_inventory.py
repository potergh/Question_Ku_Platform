"""阶段 0 Task 0.1：盘点现有练习数据（只读，不修改任何用户数据）。

统计练习/章节/题目快照/内容块数量，找出空内容、损坏图片、异常选项、
无法解析的 LaTeX 和已人工修改过的题目；记录当前数据库迁移版本。

用法：python backend/scripts/phase0_inventory.py
报告输出：backend/scripts/reports/phase0_inventory.json
"""

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "db.sqlite3"
PRACTICES_ROOT = BASE_DIR / "data" / "practices"
REPORT_DIR = Path(__file__).resolve().parent / "reports"

ASSET_REF_RE = re.compile(r"asset://practice/([^\s\)]+)")
OCR_ASSET_REF_RE = re.compile(r"/api/ocr-assets/[^\s\)]+")
MATH_INLINE_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.S)
MATH_BLOCK_RE = re.compile(r"\$\$(.+?)\$\$", re.S)


def check_math(text: str) -> list[str]:
    """粗略检查 LaTeX：美元符号不配对视为可疑。"""
    problems = []
    stripped = MATH_BLOCK_RE.sub("", text)
    stripped = MATH_INLINE_RE.sub("", stripped)
    # 剩余裸 $ 数量奇数 → 公式包装不配对
    if stripped.count("$") % 2 == 1:
        problems.append("美元符号不配对（可能存在未闭合公式）")
    return problems


def inventory() -> dict:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def one(sql: str):
        return cur.execute(sql).fetchone()[0]

    report: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(DB_PATH),
        "alembic_version": None,
        "counts": {
            "practices": one("SELECT COUNT(*) FROM practices"),
            "sections": one("SELECT COUNT(*) FROM practice_sections"),
            "questions": one("SELECT COUNT(*) FROM practice_questions"),
            "blocks": one("SELECT COUNT(*) FROM practice_content_blocks"),
        },
        "block_type_counts": {
            r["block_type"]: r["n"]
            for r in cur.execute(
                "SELECT block_type, COUNT(*) n FROM practice_content_blocks GROUP BY block_type")
        },
        "practices": [],
        "issues": {
            "empty_content": [],
            "broken_images": [],
            "external_image_refs": [],
            "suspicious_latex": [],
            "bad_options": [],
        },
        "modified_questions": [],
    }

    try:
        report["alembic_version"] = one("SELECT version_num FROM alembic_version LIMIT 1")
    except sqlite3.OperationalError:
        pass

    # 预取全部行，避免嵌套查询复用游标中断外层迭代
    practices = cur.execute(
        "SELECT id, title, subject, grade, status, page_config FROM practices ORDER BY created_at"
    ).fetchall()
    questions = cur.execute(
        "SELECT pq.id, pq.practice_id, pq.question_number, pq.question_type, "
        "pq.content_snapshot, pq.options_snapshot, pq.is_modified "
        "FROM practice_questions pq").fetchall()
    image_blocks = cur.execute(
        "SELECT cb.id, cb.block_type, cb.content, q.practice_id "
        "FROM practice_content_blocks cb JOIN practice_questions q "
        "ON cb.practice_question_id=q.id WHERE cb.block_type='image'").fetchall()

    for p in practices:
        pdir = PRACTICES_ROOT / p["id"]
        assets_dir = pdir / "assets"
        pinfo = {
            "id": p["id"], "title": p["title"], "subject": p["subject"],
            "grade": p["grade"], "status": p["status"],
            "has_page_config": p["page_config"] is not None,
            "dir_exists": pdir.exists(),
            "asset_files": len([f for f in assets_dir.iterdir() if f.is_file()]) if assets_dir.exists() else 0,
            "sections": 0, "questions": 0, "blocks": 0,
        }
        for s in cur.execute(
                "SELECT COUNT(*) FROM practice_sections WHERE practice_id=?", (p["id"],)):
            pinfo["sections"] = s[0]
        for q in cur.execute(
                "SELECT COUNT(*) FROM practice_questions WHERE practice_id=?", (p["id"],)):
            pinfo["questions"] = q[0]
        for b in cur.execute(
                "SELECT COUNT(*) FROM practice_content_blocks cb "
                "JOIN practice_questions q ON cb.practice_question_id=q.id "
                "WHERE q.practice_id=?", (p["id"],)):
            pinfo["blocks"] = b[0]
        report["practices"].append(pinfo)

    # 逐题检查内容质量
    for pq in questions:
        label = f"practice={pq['practice_id']} question={pq['id']} (#{pq['question_number']})"
        content = pq["content_snapshot"] or ""
        if not content.strip():
            report["issues"]["empty_content"].append(label)
        # 图片引用检查
        for m in ASSET_REF_RE.finditer(content):
            f = PRACTICES_ROOT / pq["practice_id"] / "assets" / m.group(1)
            if not f.exists():
                report["issues"]["broken_images"].append(f"{label} missing={m.group(1)}")
        if OCR_ASSET_REF_RE.search(content):
            report["issues"]["external_image_refs"].append(label)
        for prob in check_math(content):
            report["issues"]["suspicious_latex"].append(f"{label} {prob}")
        # 选项检查
        if pq["options_snapshot"]:
            try:
                opts = json.loads(pq["options_snapshot"])
                if not isinstance(opts, list):
                    raise ValueError("options 不是数组")
                labels = [o.get("label") for o in opts if isinstance(o, dict)]
                if len(labels) != len(set(labels)):
                    report["issues"]["bad_options"].append(f"{label} 选项标签重复: {labels}")
                for o in opts:
                    if isinstance(o, dict) and not (o.get("content") or "").strip():
                        report["issues"]["bad_options"].append(f"{label} 空选项: {o.get('label')}")
                    elif isinstance(o, dict):
                        oc = o.get("content") or ""
                        if OCR_ASSET_REF_RE.search(oc):
                            report["issues"]["external_image_refs"].append(f"{label} 选项 {o.get('label')}")
            except (ValueError, TypeError):
                report["issues"]["bad_options"].append(f"{label} 选项 JSON 无法解析")
        if pq["is_modified"]:
            report["modified_questions"].append(
                f"{label} type={pq['question_type']}")

    # 内容块里的图片资产检查
    for b in image_blocks:
        m = ASSET_REF_RE.search(b["content"] or "")
        if m:
            f = PRACTICES_ROOT / b["practice_id"] / "assets" / m.group(1)
            if not f.exists():
                report["issues"]["broken_images"].append(
                    f"block={b['id']} practice={b['practice_id']} missing={m.group(1)}")

    conn.close()

    report["issue_summary"] = {k: len(v) for k, v in report["issues"].items()}
    report["modified_question_count"] = len(report["modified_questions"])
    return report


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    report = inventory()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "phase0_inventory.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入: {out}")
    print(f"alembic 版本: {report['alembic_version']}")
    print(f"练习 {report['counts']['practices']} | 小节 {report['counts']['sections']} | "
          f"题目 {report['counts']['questions']} | 内容块 {report['counts']['blocks']}")
    print(f"内容块类型分布: {report['block_type_counts']}")
    print(f"问题统计: {report['issue_summary']}")
    print(f"已人工修改题目数: {report['modified_question_count']}")
    for p in report["practices"]:
        print(f"  - {p['title']} [{p['subject']}/{p['grade']}] "
              f"{p['questions']}题/{p['sections']}节/{p['blocks']}块 "
              f"资产{p['asset_files']}文件 status={p['status']}")


if __name__ == "__main__":
    main()
