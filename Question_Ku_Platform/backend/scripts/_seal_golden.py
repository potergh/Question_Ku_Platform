"""和平卷 golden 定版：v9（人工已核版）上位为 __golden，DB 路径同步。

前置事实（2026-09-13 核对）：
- v9 是人工逐题核过并修过 Q20/Q21/Q22 的版本，DB 当前已与它逐字段对齐；
- v10 是加固层（确定性校验 + 定向仲裁）上线后的全管线重跑，覆盖率 100%，
  但它 Q22 题干仍被切、Q19 分号抄错、Q20 答案为空 —— 数据质量不如 v9。
  所以 **golden 基线取 v9**，v10 只作为加固层的验证证据归档。

本脚本做四件事，每步都可回退：
1. 旧 __golden 归档为 __golden__20260911（项目惯例：河东卷/暑期卷都留旧版）；
2. v9 整个目录复制为 __golden（题卡图 + 插图 + extract.json）；
3. __golden/extract.json 置 confirmed=true、document_name 改名为 __golden；
4. sqlite 题库里指向 __v9 的图片路径整体改指 __golden，并逐条断言文件存在。

用法（项目根目录）::

    venv/Scripts/python.exe backend/scripts/_seal_golden.py
    venv/Scripts/python.exe backend/scripts/_seal_golden.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OCR = ROOT / "data/ocr_output"
DB = ROOT / "data/db.sqlite3"

STEM = "2022年天津市和平区中考物理一模试卷"
V9 = OCR / f"{STEM}__v9"
GOLDEN = OCR / f"{STEM}__golden"
ARCHIVE = OCR / f"{STEM}__golden__20260911"


def step(msg: str) -> None:
    print(f"  · {msg}")


def archive_old_golden(dry: bool) -> None:
    if not GOLDEN.exists():
        step("没有已存在的 __golden，跳过归档")
        return
    if ARCHIVE.exists():
        raise SystemExit(f"[FAIL] 归档目标已存在，人工确认后再跑：{ARCHIVE}")
    step(f"旧 __golden → {ARCHIVE.name}")
    if not dry:
        GOLDEN.rename(ARCHIVE)


def copy_v9_to_golden(dry: bool) -> None:
    if GOLDEN.exists() and not dry:
        raise SystemExit(f"[FAIL] {GOLDEN} 已存在，拒绝覆盖")
    step(f"{V9.name} → {GOLDEN.name}（含 questions/ 与 figures/）")
    if not dry:
        shutil.copytree(V9, GOLDEN)


def seal_json(dry: bool) -> None:
    target = GOLDEN / "extract.json"
    if dry:
        step(f"（dry-run）将置 {target} 的 confirmed=true 并改 document_name")
        return
    doc = json.loads(target.read_text(encoding="utf-8"))
    target.with_suffix(".json.prev").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    doc["confirmed"] = True
    doc["document_name"] = GOLDEN.name
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    step(f"confirmed=true，document_name={GOLDEN.name}（留档 extract.json.prev）")


def _iter_paths(value: str) -> list[str]:
    """answer_image_paths 可能是 JSON 数组，也可能是 | 或 , 分隔的字符串。"""
    text = (value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            return [str(p) for p in parsed if p]
        except json.JSONDecodeError:
            pass
    return [p.strip() for p in text.replace("|", ",").split(",") if p.strip()]


def sync_db(dry: bool) -> int:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "select id, question_number, card_image_path, answer_image_paths "
        "from questions where is_deleted=0"
    ).fetchall()
    changed = 0
    missing: list[str] = []
    for qid, number, card, answer_imgs in rows:
        updates: dict[str, str] = {}
        for field, value in (("card_image_path", card), ("answer_image_paths", answer_imgs)):
            if not value or "__v9" not in value:
                continue
            new_value = value.replace("__v9", "__golden")
            if not dry:  # 预演时目标目录还没复制出来，文件必然不存在
                for piece in _iter_paths(new_value):
                    if not Path(piece).exists():
                        missing.append(f"Q{number:03d} {field}: {piece}")
            updates[field] = new_value
        if not updates or dry:
            continue
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"update questions set {sets}, updated_at=datetime('now') where id=?",
            (*updates.values(), qid),
        )
        changed += 1
    if missing:
        conn.rollback()
        conn.close()
        raise SystemExit("[FAIL] 改指后文件不存在，已回滚：\n  " + "\n  ".join(missing[:10]))
    if not dry:
        conn.commit()
    conn.close()
    step(f"DB 图片路径 __v9 → __golden：{changed} 行（文件存在性已逐条断言）")
    return changed


def verify(dry: bool) -> None:
    if dry:
        return
    doc = json.loads((GOLDEN / "extract.json").read_text(encoding="utf-8"))
    assert doc["confirmed"] is True, "confirmed 未置位"
    assert doc["question_count"] == 26, f"题数异常：{doc['question_count']}"
    for item in doc["items"]:
        card = item.get("card_image")
        if not card:
            continue
        # extract.json 里的 card_image 是相对产物目录的路径。
        full = Path(card) if Path(card).is_absolute() else GOLDEN / card
        if not full.exists():
            raise SystemExit(f"[FAIL] 题卡缺失：{card}")
    step("回验：26 题、confirmed=true、题卡图齐全")
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "select question_number, card_image_path from questions "
        "where is_deleted=0 and card_image_path like '%__v9%'"
    ).fetchall()
    conn.close()
    if rows:
        raise SystemExit(f"[FAIL] 仍有 {len(rows)} 行指向 __v9：{[r[0] for r in rows]}")
    step("回验：DB 中无残留 __v9 路径")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not V9.exists():
        print(f"[FAIL] 源目录不存在：{V9}")
        return 2
    print(("[预演] " if args.dry_run else "") + "和平卷 golden 定版")
    archive_old_golden(args.dry_run)
    copy_v9_to_golden(args.dry_run)
    seal_json(args.dry_run)
    sync_db(args.dry_run)
    verify(args.dry_run)
    print("\n完成。下一步：git commit + 打 tag 固化。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
