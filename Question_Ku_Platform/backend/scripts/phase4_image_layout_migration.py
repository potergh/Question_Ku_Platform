"""阶段 4 Task 4.7：为所有 image 节点补 layout 默认值（"row"），并校验多图题目。

用法（在 backend 目录执行）：
    python scripts/phase4_image_layout_migration.py              # 试运行（只统计不写入）
    python scripts/phase4_image_layout_migration.py --apply      # 正式迁移（自动备份）
    python scripts/phase4_image_layout_migration.py --apply --practice <id>   # 单份重试

迁移只补 image 节点的 layout 字段；幂等；单份失败不影响其他练习。
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
from app.models.practice import Practice, PracticeQuestion  # noqa: E402
from app.services.rich_document import add_image_layout_default, serialize  # noqa: E402

REPORT_DIR = BACKEND_DIR / "scripts" / "reports"


def make_backup(data_dir: Path, db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = data_dir / "backups" / f"phase4_{stamp}"
    dest.mkdir(parents=True)
    shutil.copy2(db_path, dest / db_path.name)
    return dest


async def run(args) -> dict:
    db_url = f"sqlite+aiosqlite:///{settings.db_path}"
    engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(settings.db_path),
        "backup_path": None,
        "practices": 0, "questions": 0, "image_nodes": 0, "patched_nodes": 0,
        "multi_image_questions": 0, "failed": [],
    }

    if args.apply and not args.no_backup:
        backup = make_backup(settings.data_dir, settings.db_path)
        report["backup_path"] = str(backup) if backup else None
        print(f"[备份] {report['backup_path']}")

    async with factory() as db:
        q = select(PracticeQuestion).where(PracticeQuestion.rich_document.is_not(None))
        if args.practice:
            q = q.where(PracticeQuestion.practice_id == args.practice)
        questions = list((await db.execute(q)).scalars().all())
        for pq in questions:
            try:
                doc = json.loads(pq.rich_document)
                if not isinstance(doc, dict) or not doc.get("content"):
                    continue
                imgs = [n for n in doc["content"] if n.get("type") == "image"]
                n_img = len(imgs)
                if n_img >= 2:
                    report["multi_image_questions"] += 1
                n_patch = add_image_layout_default(doc)
                report["questions"] += 1
                report["image_nodes"] += n_img
                report["patched_nodes"] += n_patch
                if args.apply and n_patch > 0:
                    pq.rich_document = serialize(doc)
            except Exception as e:  # noqa: BLE001
                report["failed"].append({"id": pq.id, "error": str(e)[:200]})
        if args.apply:
            await db.commit()

    report["practices"] = len({pq.practice_id for pq in questions})
    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "phase4_image_layout_migration_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[报告] {out}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="正式迁移（自动备份）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份")
    ap.add_argument("--practice", help="只处理指定练习")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
