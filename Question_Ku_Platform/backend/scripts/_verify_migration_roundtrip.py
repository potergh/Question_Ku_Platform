"""迁移往返验证：upgrade → downgrade → upgrade 三步都要通。

存在的意义：Alembic 迁移最常见的退化不是 upgrade 跑不起来，而是 **downgrade
与 upgrade 不对称**（例如 upgrade 换成了 add_column，downgrade 还是 alter_column）。
这种 bug 单跑 `upgrade head` 永远发现不了，直到有人降级一次再升回来，
才会撞上 `duplicate column name`。

做法：复制真实库为探针库 → `stamp` 到目标迁移的父版本 → 手工把该迁移引入的列
删掉（模拟「该迁移之前」的 schema）→ 跑 upgrade / downgrade / upgrade。

用法：
    python -m scripts._verify_migration_roundtrip                 # 默认验 db24daa9df4a
    python -m scripts._verify_migration_roundtrip d4e5f6a7b8c9
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

PROBE_DB = settings.data_dir / "_migrate_probe.sqlite3"

# 每个迁移引入的列，用于把探针库回退成「该迁移之前」的样子。
# 只登记本仓库会被回退重建的迁移；不在表里的迁移也能验，但需要先手工改 schema。
INTRODUCED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "db24daa9df4a": [("jobs", "cancelled"), ("tags", "subject")],
    "d4e5f6a7b8c9": [("questions", "answer_image_paths")],
    "c1d2e3f4a5b6": [("settings", "ai_review_prompt")],
}


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def _columns(db: Path, table: str) -> list[str]:
    con = sqlite3.connect(db)
    try:
        return [row[1] for row in con.execute(f"pragma table_info({table})")]
    finally:
        con.close()


def _has_table(db: Path, table: str) -> bool:
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "select name from sqlite_master where type='table' and name=?", (table,)
        ).fetchone()
        return row is not None
    finally:
        con.close()


def alembic(*argv: str, db: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DB_PATH"] = str(db)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *argv],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_step(title: str, *argv: str, db: Path, expect_ok: bool = True) -> None:
    proc = alembic(*argv, db=db)
    combined = f"{proc.stdout or ''}{proc.stderr or ''}"
    if proc.returncode != 0:
        tail = "\n".join(line for line in combined.strip().splitlines()[-4:])
        if expect_ok:
            _fail(f"{title} → 退出码 {proc.returncode}\n{tail}")
        print(f"[EXPECTED-FAIL] {title} → 退出码 {proc.returncode}")
        print(f"                 {tail.splitlines()[-1] if tail else ''}")
        return
    _ok(title)


def resolve_parent(revision: str) -> str:
    """从迁移文件里读出 down_revision。"""
    for path in (BACKEND_DIR / "alembic" / "versions").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if f"'{revision}'" not in text and f'"{revision}"' not in text:
            continue
        for line in text.splitlines():
            if "down_revision" in line and "=" in line:
                value = line.split("=", 1)[1].strip()
                return value.strip("'\"")
    _fail(f"找不到迁移 {revision} 的 down_revision")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("revision", nargs="?", default="db24daa9df4a")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="跑完保留探针库，便于手工查看 schema",
    )
    args = parser.parse_args()

    target = args.revision
    parent = resolve_parent(target)
    print(f"验证迁移 {target}（父版本 {parent}）\n")

    shutil.copy2(settings.db_path, PROBE_DB)
    _ok(f"探针库就位：{PROBE_DB.name}（源自 {settings.db_path.name}）")

    run_step(f"stamp {parent}（只回退版本号，不动 schema）", "stamp", parent, db=PROBE_DB)

    dropped = INTRODUCED_COLUMNS.get(target)
    if dropped:
        con = sqlite3.connect(PROBE_DB)
        try:
            for table, column in dropped:
                if not _has_table(PROBE_DB, table):
                    con.close()
                    _fail(f"探针库里没有 {table} 表，无法模拟迁移前状态")
                if column in _columns(PROBE_DB, table):
                    con.execute(f"alter table {table} drop column {column}")
            con.commit()
        finally:
            con.close()
        _ok(f"已删掉 {target} 引入的列：{dropped}")
    else:
        print(f"[WARN] 未登记 {target} 引入的列，直接按现有 schema 验证")

    run_step("第 1 步 upgrade", "upgrade", target, db=PROBE_DB)
    for table, column in INTRODUCED_COLUMNS.get(target, []):
        if column not in _columns(PROBE_DB, table):
            _fail(f"upgrade 后 {table}.{column} 仍不存在")
    _ok(f"upgrade 后列已就位：{INTRODUCED_COLUMNS.get(target)}")

    run_step("第 2 步 downgrade", "downgrade", parent, db=PROBE_DB)
    for table, column in INTRODUCED_COLUMNS.get(target, []):
        if column in _columns(PROBE_DB, table):
            _fail(f"downgrade 后 {table}.{column} 仍在 —— 降级不彻底")
    _ok("downgrade 后列已清除（对称）")

    run_step("第 3 步再 upgrade（旧版会在这里报 duplicate column）", "upgrade", target, db=PROBE_DB)
    for table, column in INTRODUCED_COLUMNS.get(target, []):
        if column not in _columns(PROBE_DB, table):
            _fail(f"二次 upgrade 后 {table}.{column} 仍不存在")
    _ok("二次 upgrade 后列重新就位")

    if args.keep:
        print(f"\n探针库保留：{PROBE_DB}")
    else:
        PROBE_DB.unlink(missing_ok=True)
        _ok("探针库已清理")

    print(f"\n=== 迁移 {target} 往返验证通过 ===")


if __name__ == "__main__":
    main()
