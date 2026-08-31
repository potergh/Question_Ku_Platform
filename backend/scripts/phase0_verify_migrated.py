"""阶段 0 Task 0.6：迁移后的旧练习端到端验证（只读，不改库）。

对全部 migration_status='done' 的练习：渲染预览（数页数）+ 生成 Word，
证明迁移后的旧练习仍可打开、预览、导出。
"""

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.models.practice import Practice  # noqa: E402
from app.routers.practices import _get_practice_full  # noqa: E402
from app.services import render_service, docx_export, block_service  # noqa: E402


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    async with async_session_factory() as db:
        practices = (await db.execute(
            select(Practice).where(Practice.migration_status == "done"))).scalars().all()
        ok = True
        for p in practices:
            full = await _get_practice_full(db, p.id)
            for sec in full.sections:
                for pq in sec.questions:
                    if not pq.blocks:   # 只读检查缺块情况，不物化
                        print(f"  [警告] {p.title} 题目 {pq.id} 无内容块")
            html = render_service.build_practice_html(full, p.id)
            rs = render_service.render_settings(full)
            pdf = await render_service.render_pdf_bytes(html, rs)
            docx_bytes = await asyncio.to_thread(docx_export.build_docx, full, p.id)
            n_q = sum(len(s.questions) for s in full.sections)
            good = len(pdf) > 1000 and len(docx_bytes) > 1000 and "%PDF" in pdf[:8].decode("latin-1")
            ok &= good
            print(f"[{'OK' if good else 'FAIL'}] {p.title}：{n_q} 题，"
                  f"PDF {len(pdf)//1024}KB，Word {len(docx_bytes)//1024}KB")
        print("结论:", "全部可预览/导出" if ok else "存在失败")


if __name__ == "__main__":
    asyncio.run(main())
