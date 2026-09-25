"""F07 排版规则标定样本：把和平卷 26 题落成一份练习。

用途（用户决策 2026-09-20）：F07 的排版规则（选项单/双/四列阈值、分页保护、
题型分节）必须以真实样本共同制定，指定样本为
`data/ocr_output/2022年天津市和平区中考物理一模试卷`（权威内容在其 `__golden` 定版）。

该卷题目已经 `_sync_extract_to_db.py` 同步进题库，本脚本只负责把它们组装成一份
**练习**（快照 + 图片资产拷贝），供排版规则逐条标定与验收。

幂等：同名练习已存在则跳过，不重复创建。
安全：写库前自动备份 `data/db.sqlite3` 到 `data/backups/`。

用法（工作目录 backend/）：
    python scripts/f07_make_calibration_practice.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import Question, Source  # noqa: E402
from app.models.practice import Practice  # noqa: E402
from app.services import practice_service  # noqa: E402

TITLE = "和平卷·F07 排版规则标定"
SOURCE_HINT = "和平区"


def backup_db() -> Path | None:
    """写库前备份（仓库既有约定：改数据前留快照）。"""
    db_path = settings.db_path
    if not db_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = settings.data_dir / "backups" / f"f07_calibration_{stamp}" / db_path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, dest)
    return dest


async def _plan() -> tuple[str | None, list[str]]:
    """只读阶段：返回 (已存在练习 id, 待入册题目 id 列表)。"""
    async with async_session_factory() as db:
        existing = (await db.execute(
            select(Practice).where(Practice.title == TITLE)
        )).scalars().first()
        if existing:
            return existing.id, []

        sources = (await db.execute(
            select(Source).where(Source.filename.contains(SOURCE_HINT))
        )).scalars().all()
        qids: list[str] = []
        for src in sources:
            rows = (await db.execute(
                select(Question)
                .where(Question.source_id == src.id, Question.is_deleted == False)  # noqa: E712
                .order_by(Question.question_number)
            )).scalars().all()
            print(f"[INFO] 来源 {src.filename}：{len(rows)} 题")
            qids.extend(q.id for q in rows)
        return None, qids


async def _create(qids: list[str]) -> int:
    """写入阶段：新开 session 重新加载题目并创建练习。"""
    async with async_session_factory() as db:
        questions = (await db.execute(
            select(Question).where(Question.id.in_(qids))
        )).scalars().all()
        practice = await practice_service.create_practice_from_questions(
            db, TITLE, "F07 排版规则标定（选项分列 / 分页保护 / 题型分节）",
            "物理", None, list(questions),
        )
        await db.commit()
        assets = practice_service.practice_assets_dir(practice.id)
        print(f"[DONE] 练习 {practice.id}「{practice.title}」"
              f"，{len(questions)} 题，资产目录 {assets}")
    return 0


async def main() -> int:
    existing_id, qids = await _plan()
    if existing_id:
        print(f"[SKIP] 已存在同名练习 {existing_id}（{TITLE}），未重复创建")
        return 0
    if not qids:
        print("[ERROR] 没有可用题目：题库里找不到该来源或题目已全部删除", file=sys.stderr)
        return 1

    # 备份必须在无活动连接时做，避免复制到未落盘的中间态
    backup = backup_db()
    if backup:
        print(f"[INFO] 已备份数据库 → {backup}")
    return await _create(qids)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
