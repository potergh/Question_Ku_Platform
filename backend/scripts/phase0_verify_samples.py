"""端到端验证补录样题：建临时练习→迁移/渲染检查→删除（自清理）。"""
import asyncio
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import Question, Source  # noqa: E402
from app.models.practice import Practice  # noqa: E402
from app.routers.practices import _get_practice_full  # noqa: E402
from app.services import practice_service, render_service, block_service  # noqa: E402


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pid = None
    try:
        async with async_session_factory() as db:
            source = (await db.execute(select(Source).where(
                Source.filename == "手动补录样题（公式+选项图）"))).scalar_one()
            qs = (await db.execute(select(Question).where(
                Question.source_id == source.id).order_by(Question.question_number))).scalars().all()
            assert len(qs) == 4, f"样题数 {len(qs)} != 4"
            practice = await practice_service.create_practice_from_questions(
                db, "临时-样题验证", None, None, None, list(qs))
            pid = practice.id
            nums = [pq.question_number for s in practice.sections for pq in s.questions]
            print("题号:", sorted(nums), "→", "OK" if sorted(nums) == [1, 2, 3, 4] else "FAIL")

        async with async_session_factory() as db:
            full = await _get_practice_full(db, pid)
            for sec in full.sections:
                for pq in sec.questions:
                    if not pq.blocks:
                        await block_service.materialize_blocks(db, pq)
            await db.commit()
            full = await _get_practice_full(db, pid)
            html = render_service.build_practice_html(full, pid)
            checks = {
                "无 Markdown 图残留": "![" not in html,
                "选项图已内联 <img>": html.count("<img") >= 5,   # 4 选项图 + 1 题干图
                "题干图已内联": "Q_incline_01.webp" in html,
                "KaTeX 公式渲染": "katex" in html,
                "留白无横线": "border-bottom" not in html,
            }
            for name, ok in checks.items():
                print(f"[{'OK' if ok else 'FAIL'}] {name}")
            assert all(checks.values()), "存在检查失败"
        print("验证通过")
    finally:
        if pid:
            async with async_session_factory() as db:
                p = await db.get(Practice, pid)
                if p:
                    await db.delete(p)
                    await db.commit()
            d = settings.data_dir / "practices" / pid
            if d.exists():
                shutil.rmtree(d)
            print(f"已清理临时练习 {pid}")


if __name__ == "__main__":
    asyncio.run(main())
