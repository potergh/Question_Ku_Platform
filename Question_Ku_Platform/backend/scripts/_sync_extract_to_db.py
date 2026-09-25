"""把某份 extract 产物同步进 sqlite 题库（重跑后换基线的正规入口）。

以前每换一次基线就手写一个一次性脚本（`_fix_q21_q22_boundary.py`、
`_finalize_q20_and_sync_db.py`、`_seal_golden.py`…），逻辑各不相同又没法复用。
本脚本把这件事收敛成一个可重复执行的入口，并守住五条底线：

1. **先定卷**：产物目录名反查 `sources`，锁定到唯一一份卷才继续；
2. **先看闸门**：产物 audit.blocked 为真时拒绝同步（除非 --force）；
3. **先看确认态**：产物 confirmed 为假时只预演（除非 --allow-unconfirmed）；
4. **先备份**：动库之前把 db.sqlite3 复制一份带时间戳的副本；
5. **先断言**：改指后的每个图片路径都必须真实存在，否则整体回滚。

第 1 条是补上的漏洞。本题库是多卷共存的，`questions` 表按 `question_number`
编号 —— 题号在**卷内**唯一，跨卷必然重复（和平卷 1~26、河东卷 1~25）。
本脚本早期版本按题号全库匹配，于是拿河东卷产物跑一次就会把河东卷的 Q1~Q25
写进和平卷的 Q1~Q25，`--update-source-dir` 还会把和平卷的入口改指到河东卷目录。
库里只有一份卷时不会暴露，第二份卷入库时就会静默毁数据。现在按
`<上传文件名去扩展名>` 前缀把产物锚定到 `sources.filename`，锚不唯一就拒绝执行。

适用范围（**不是入库工具**）：本脚本只 update 已存在的题，不 insert。
把一份**新卷**首次入库走后端 `/api/sources/{id}/extract` + 前端确认，
那个入口负责建题、分配 source_id、软删旧版。

用法（项目根目录）::

    venv/Scripts/python.exe backend/scripts/_sync_extract_to_db.py <产物目录名>
    venv/Scripts/python.exe backend/scripts/_sync_extract_to_db.py …__v12 --dry-run
    venv/Scripts/python.exe backend/scripts/_sync_extract_to_db.py …__v12 --force

同名文件上传过多次、卷名反查不唯一时，用 `--source-id` 显式指定。
只有 dry-run 会打印将要做什么；正式执行会写库并打印改动行数。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OCR = ROOT / "data/ocr_output"
DB = ROOT / "data/db.sqlite3"

SYNC_FIELDS = (
    "content",
    "options",
    "answer",
    "explanation",
    "card_image_path",
    "answer_image_paths",
)


def _abs(document_dir: Path, value: str | None) -> str | None:
    """extract.json 里的图片路径是相对产物目录的，写库必须是绝对路径。"""
    if not value:
        return None
    path = Path(value)
    return str(path if path.is_absolute() else document_dir / path)


def _blank(value) -> bool:
    """None / "" / "[]" / "{}" 都是「没有值」，不该算差异。"""
    if not value:
        return True
    try:
        return json.loads(value) in (None, [], {}, "")
    except (json.JSONDecodeError, TypeError):
        return False


def _same(a, b) -> bool:
    """逐字段比较库值与产物值，三种「字面不同但语义相同」必须放行。

    1. JSON 列：库里存的是 ensure_ascii=True 的转义串（"\\u533b…"），
       重新序列化出来是中文原文 —— 按字符串比会谎报「23 题需要更新」；
    2. 空值族：None 与 "[]" 都表示没有选项 / 没有答案图；
    3. 路径：Windows 下 / 与 \\ 混用是同一个文件。
    """
    if (a or None) == (b or None):
        return True
    if not (a and b):
        return _blank(a) and _blank(b)
    if ("/" in a or "\\" in a) and ("/" in b or "\\" in b):
        if os.path.normpath(a).lower() == os.path.normpath(b).lower():
            return True
    try:
        return json.loads(a) == json.loads(b)
    except (json.JSONDecodeError, TypeError):
        return False


def _iter_figures(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def _resolve_source(
    conn: sqlite3.Connection, document_name: str, explicit: str | None
) -> tuple[str, str] | None:
    """把产物目录名锚定到唯一一个 source，锚不唯一就返回 None（调用方拒绝执行）。

    锚定规则：产物目录名是 `<上传文件名去扩展名>` 或 `<它>__<后缀>`
    （后端建目录用 `Path(file_path).stem`，换基线时人工加后缀）。
    所以拿 `Path(sources.filename).stem` 做前缀匹配，不猜切分规则 ——
    `__golden__v6` 这种双后缀、卷名里本身带下划线都能正确落到同一个 source。
    """
    rows = conn.execute("select id, filename from sources").fetchall()
    if not rows:
        print("[FAIL] sources 表是空的，无法锚定产物归属。")
        return None

    if explicit:
        for sid, fname in rows:
            if sid == explicit:
                return sid, fname
        print(f"[FAIL] --source-id {explicit!r} 不在 sources 表里。现有：")
        for sid, fname in rows:
            print(f"  {sid}  {fname}")
        return None

    matched = [
        (sid, fname)
        for sid, fname in rows
        if document_name == Path(fname).stem
        or document_name.startswith(Path(fname).stem + "__")
    ]
    if len(matched) == 1:
        return matched[0]

    if not matched:
        print(f"[FAIL] 产物目录名 {document_name!r} 找不到对应的 source。")
        print("       目录名必须是 <上传文件名去扩展名> 或 <它>__<后缀>。现有 source：")
    else:
        print(f"[FAIL] 产物目录名 {document_name!r} 匹配到 {len(matched)} 个 source，无法判定：")
    for sid, fname in matched or rows:
        print(f"  {sid}  {fname}")
    print("       确认目标卷后用 --source-id 显式指定。")
    if not matched:
        print("       若这是**一份新卷**：本脚本只更新已有题、不新建，"
              "请走后端 /api/sources/{id}/extract + 前端确认入库。")
    return None


def _load_questions(
    conn: sqlite3.Connection, source_id: str
) -> tuple[dict[int, tuple[str, ...]], list[int]]:
    """只取本 source 的题。题号跨卷重复，不锁 source 就会串到别的卷。"""
    rows = conn.execute(
        "select id, question_number, content, options, answer, explanation, "
        "card_image_path, answer_image_paths from questions "
        "where is_deleted=0 and source_id=?",
        (source_id,),
    ).fetchall()
    out: dict[int, tuple[str, ...]] = {}
    dups: list[int] = []
    for row in rows:
        if row[1] in out:
            dups.append(row[1])
        out[row[1]] = row
    return out, dups


def main() -> int:
    parser = argparse.ArgumentParser(description="把 extract 产物同步进 sqlite 题库")
    parser.add_argument("document", help="产物目录名，如 2022年…一模试卷__v12")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    parser.add_argument("--force", action="store_true", help="产物被闸门阻断时也同步")
    parser.add_argument(
        "--allow-unconfirmed",
        action="store_true",
        help="产物 confirmed 为假时也同步（默认只预演）",
    )
    parser.add_argument(
        "--update-source-dir",
        action="store_true",
        help="同时把 sources.ocr_result_path 指向本产物目录（换基线时必须做）",
    )
    parser.add_argument(
        "--source-id",
        default=None,
        help="显式指定 source（卷名反查不唯一时用）",
    )
    args = parser.parse_args()

    # 必须解析成绝对路径：sources.ocr_result_path 被后端用 Path() 直接读，
    # 相对路径会跟着进程工作目录跑（后端常从 backend/ 启动）→ 审阅页 404。
    document_dir = (OCR / args.document).resolve()
    extract_path = document_dir / "extract.json"
    if not extract_path.exists():
        print(f"[FAIL] 找不到产物：{extract_path}")
        return 2

    # 先锚卷、再读内容。目录名对不上任何 source 是最容易犯的手误（复制了别的卷的
    # 目录名），放在题数/闸门检查之后会被「覆盖率不足」这类提示带偏方向。
    conn = sqlite3.connect(DB)

    def _abort(message: str) -> int:
        conn.close()
        print(message)
        return 2

    resolved = _resolve_source(conn, args.document, args.source_id)
    if resolved is None:
        conn.close()
        return 2
    source_id, source_filename = resolved

    doc = json.loads(extract_path.read_text(encoding="utf-8"))
    items = [item for item in doc.get("items", []) if not item.get("excluded")]
    if not items:
        return _abort("[FAIL] 产物里没有可用题目")

    audit = doc.get("audit") or {}
    if audit.get("blocked") and not args.force:
        return _abort(
            f"[FAIL] 产物被审计闸门阻断（{audit.get('reasons') or '原因见 audit'}）。"
            f"确认要同步请加 --force。"
        )
    if not doc.get("confirmed") and not args.allow_unconfirmed:
        print(
            "[提示] 产物 confirmed=false（未经人工终审）。\n"
            "       默认不写入；确认后加 --allow-unconfirmed，或先在审阅页点确认。"
        )
        if not args.dry_run:
            conn.close()
            return 2

    existing, dups = _load_questions(conn, source_id)
    if dups:
        conn.close()
        print(f"[FAIL] source 内题号重复：{sorted(set(dups))}。按题号定位会静默覆盖，已中止。")
        return 2
    if not existing:
        conn.close()
        print(
            f"[FAIL] source {source_id[:8]}…（{source_filename}）名下没有未删除的题目。\n"
            "       本脚本只 update 已有题、不 insert —— 新卷首次入库请走后端\n"
            "       /api/sources/{id}/extract + 前端确认。"
        )
        return 2

    updates: list[tuple] = []
    missing: list[str] = []
    skipped: list[int] = []
    for item in items:
        number = item.get("question_number")
        row = existing.get(number)
        if row is None:
            skipped.append(number)
            continue
        card = _abs(document_dir, item.get("card_image"))
        figures = [_abs(document_dir, f) for f in _iter_figures(item.get("answer_figures"))]
        for path in [card, *figures]:
            if path and not Path(path).exists():
                missing.append(f"Q{number:03d}: {path}")
        values = (
            item.get("content"),
            json.dumps(item.get("options"), ensure_ascii=False)
            if item.get("options")
            else None,
            item.get("answer"),
            item.get("explanation"),
            card,
            json.dumps([f for f in figures if f], ensure_ascii=False) if figures else None,
        )
        if all(_same(value, current) for value, current in zip(values, row[2:])):
            continue
        # 末尾三列：行 id、source_id、题号（题号只用于打印，不参与定位）
        updates.append((*values, row[0], source_id, number))

    if missing:
        conn.close()
        print("[FAIL] 以下图片路径在产物目录里不存在，已中止：")
        for line in missing[:10]:
            print("  -", line)
        return 2

    print(f"产物：{document_dir.name}")
    print(f"锚定 source：{source_id}  ({source_filename})")
    print(f"本卷库内 {len(existing)} 题 | 产物 {len(items)} 题 | 需要更新 {len(updates)} 题")
    if skipped:
        print(f"  题库里没有对应题号、跳过：{skipped}")
    # sources.ocr_result_path 是审阅页与「确认入库」的入口。它指向旧目录时，
    # 用户在前端点一次确认就会用旧内容覆盖刚同步好的题目 —— 换基线必须一起改。
    # 只查本 source：改了别人的入口等于把那份卷的产物指到这份卷来。
    source_rows = conn.execute(
        "select id, ocr_result_path from sources where id=?", (source_id,)
    ).fetchall()
    stale_sources = [
        (sid, old)
        for sid, old in source_rows
        if old and os.path.normpath(old).lower() != os.path.normpath(str(document_dir)).lower()
    ]
    if args.update_source_dir and stale_sources:
        print(f"  将把 source 入口 {stale_sources[0][1].split('ocr_output')[-1]} → 本目录")

    if not updates and not (args.update_source_dir and stale_sources):
        print("内容与图片路径已完全一致，无需同步。")
        conn.close()
        return 0

    if args.dry_run:
        for values in updates[:10]:
            print(f"  将更新 Q{values[-1]}: answer={(values[2] or '')[:40]!r}")
        conn.close()
        print("\n（dry-run，未写库）")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB.with_name(f"db.sqlite3.bak_{stamp}")
    shutil.copy2(DB, backup)
    print(f"已备份数据库 → {backup.name}")

    try:
        if updates:
            conn.executemany(
                "update questions set content=?, options=?, answer=?, explanation=?, "
                "card_image_path=?, answer_image_paths=?, updated_at=datetime('now') "
                "where id=? and source_id=?",
                [values[:-1] for values in updates],
            )
        if args.update_source_dir:
            for sid, _old in stale_sources:
                conn.execute(
                    "update sources set ocr_result_path=? where id=?",
                    (str(document_dir), sid),
                )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        conn.close()
        print(f"[FAIL] 写库失败已回滚：{exc}")
        return 2
    conn.close()
    print(f"已同步 {len(updates)} 题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
