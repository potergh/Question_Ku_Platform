"""阶段 0 Task 0.5：旧练习批量迁移到新富文本文档结构（可预检、可重试、可回退）。

用法（在 backend 目录执行）：
    python scripts/phase0_migrate.py                 # 默认试运行（只检查不写入）
    python scripts/phase0_migrate.py --apply         # 正式迁移（自动先备份）
    python scripts/phase0_migrate.py --apply --practice <id>   # 单份重试
    python scripts/phase0_migrate.py --apply --no-backup       # 跳过备份（已手动备份时）

备份位置：data/backups/phase0_<时间戳>/（数据库文件 + 练习资产目录）。
报告输出：backend/scripts/reports/phase0_migration_report.json

迁移只写新字段（rich_document / 迁移状态），旧字段保持原样；
重复执行幂等；单份失败标记 failed 并保留原数据，修复后可重试。
"""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.models.practice import Practice  # noqa: E402
from app.services import doc_migration  # noqa: E402

REPORT_DIR = BACKEND_DIR / "scripts" / "reports"


def make_backup(data_dir: Path, db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = data_dir / "backups" / f"phase0_{stamp}"
    dest.mkdir(parents=True)
    shutil.copy2(db_path, dest / db_path.name)
    practices_dir = data_dir / "practices"
    if practices_dir.exists():
        shutil.copytree(practices_dir, dest / "practices")
    return dest


async def run(args) -> dict:
    db_url = f"sqlite+aiosqlite:///{settings.db_path}"
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    report: dict = {
        "mode": "apply" if args.apply else "dry-run",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(settings.db_path),
        "backup_path": None,
        "practices": [],
    }

    if args.apply and not args.no_backup:
        backup = make_backup(settings.data_dir, settings.db_path)
        report["backup_path"] = str(backup) if backup else None
        print(f"[备份] {report['backup_path']}")

    async with factory() as db:
        q = select(Practice).order_by(Practice.created_at)
        if args.practice:
            q = q.where(Practice.id == args.practice)
        practices = list((await db.execute(q)).scalars().all())

    ok = failed = 0
    for p in practices:
        entry = {"id": p.id, "title": p.title, "status": None,
                 "questions": 0, "warnings": [], "error": None}
        try:
            async with factory() as db:
                practice = await doc_migration.load_practice_for_migration(db, p.id)
                if not practice:
                    raise RuntimeError("练习不存在")
                if args.apply:
                    res = await doc_migration.migrate_practice(db, practice)
                    await db.commit()
                    entry["status"] = "done"
                else:
                    res = await doc_migration.dry_run_practice(db, practice)
                    await db.rollback()   # 试运行不落库
                    entry["status"] = "dry-run"
                entry["questions"] = res["questions"]
                entry["warnings"] = res["warnings"]
                ok += 1
        except Exception as e:  # 单份失败不阻断其他练习
            entry["status"] = "failed"
            entry["error"] = f"{type(e).__name__}: {e}"
            failed += 1
            if args.apply:
                async with factory() as db2:
                    pr = await db2.get(Practice, p.id)
                    if pr:
                        pr.migration_status = "failed"
                        pr.migration_note = entry["error"]
                        await db2.commit()
        report["practices"].append(entry)
        wcnt = len(entry["warnings"])
        extra = f" 错误={entry['error']}" if entry["error"] else ""
        print(f"  [{entry['status']}] {p.title} 题目={entry['questions']} 警告={wcnt}{extra}")

    report["summary"] = {"total": len(practices), "ok": ok, "failed": failed,
                         "finished_at": datetime.now().isoformat(timespec="seconds")}
    await engine.dispose()
    return report


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="阶段 0 旧练习迁移工具")
    parser.add_argument("--apply", action="store_true", help="正式写入（默认试运行）")
    parser.add_argument("--practice", help="只处理指定练习 ID（失败重试）")
    parser.add_argument("--no-backup", action="store_true", help="跳过备份")
    parser.add_argument("--db", help="数据库路径覆盖")
    parser.add_argument("--data-dir", help="数据目录覆盖")
    args = parser.parse_args()

    if args.db:
        settings.db_path = Path(args.db)
    if args.data_dir:
        settings.data_dir = Path(args.data_dir)

    print(f"模式: {'正式迁移' if args.apply else '试运行（不写入）'}  数据库: {settings.db_path}")
    report = asyncio.run(run(args))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "phase0_migration_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    s = report["summary"]
    print(f"完成：共 {s['total']} 份，成功 {s['ok']}，失败 {s['failed']}")
    print(f"报告: {out}")


if __name__ == "__main__":
    main()
