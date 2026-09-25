"""阶段 0 补丁：修复存量练习中的 /api/ocr-assets 外部图片引用（题干/选项/块）。

根因：早期创建路径题干只处理 asset://，部分题库题 content 存的是
/api/ocr-assets/<source_id>/figures/… 形式，未迁入练习资产。
本脚本对全部练习幂等修复：引用迁入练习资产并改写，同步快照与富文本文档。
运行前先自动备份数据库。
"""

import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models.practice import Practice  # noqa: E402
from app.routers.practices import _get_practice_full  # noqa: E402
from app.services import practice_service  # noqa: E402
from app.services.rich_document import sync_rich_document  # noqa: E402

BAD = "/api/ocr-assets"


async def fix_practice(db, p: Practice) -> int:
    """返回修复的题目数。"""
    full = await _get_practice_full(db, p.id)
    fixed = 0
    for sec in full.sections:
        for pq in sec.questions:
            changed = False
            # 题干快照
            if pq.content_snapshot and BAD in pq.content_snapshot:
                new = await practice_service.migrate_option_refs(db, p.id, pq.content_snapshot)
                if new != pq.content_snapshot:
                    pq.content_snapshot = new
                    changed = True
            # 题干文本块（已物化时渲染以块为准）
            block_changed = False
            for b in pq.blocks or []:
                if b.block_type == "text" and b.content and BAD in b.content:
                    new = await practice_service.migrate_option_refs(db, p.id, b.content)
                    if new != b.content:
                        b.content = new
                        block_changed = True
            if block_changed:
                sync_rich_document(pq, sorted(pq.blocks, key=lambda b: b.position))
                changed = True
            # 选项（块 + 快照；内部同步 options_snapshot 与 rich_document）
            if await practice_service.migrate_question_option_blocks(db, p.id, pq):
                changed = True
            elif pq.options_snapshot and BAD in str(pq.options_snapshot):
                # 快照残留外部引用：块已迁移则直接以块回填（避免重复复制资产），
                # 否则迁入快照本身。
                import json as _json
                opts_block = next((b for b in pq.blocks or [] if b.block_type == "options"), None)
                if opts_block and BAD not in (opts_block.content or ""):
                    pq.options_snapshot = _json.loads(opts_block.content)
                else:
                    new_opts = []
                    for o in pq.options_snapshot:
                        c = await practice_service.migrate_option_refs(db, p.id, o.get("content"))
                        new_opts.append({**o, "content": c} if c != o.get("content") else o)
                    pq.options_snapshot = new_opts
                changed = True
            if changed:
                fixed += 1
    return fixed


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    db_file = settings.data_dir / "db.sqlite3"
    backup = db_file.with_name(f"db.sqlite3.bak_badrefs_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(db_file, backup)
    print(f"已备份数据库 → {backup.name}")

    total = 0
    async with async_session_factory() as db:
        practices = (await db.execute(select(Practice))).scalars().all()
        for p in practices:
            n = await fix_practice(db, p)
            if n:
                print(f"  [修复] {p.title}：{n} 题")
                total += n
        await db.commit()
    print(f"共修复 {total} 题" if total else "无需修复")


if __name__ == "__main__":
    asyncio.run(main())
