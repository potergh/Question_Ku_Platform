"""Initialize preset physics knowledge-point tags.

Run once to populate the default tag tree for physics.
Usage: python -m app.init_tags
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import async_session_factory, init_db
from app.models import Tag

# Physics knowledge point tree
PHYSICS_TAGS = {
    "knowledge": [
        ("力学", None, [
            ("牛顿运动定律", None),
            ("万有引力", None),
            ("功和能", None),
            ("动量守恒", None),
            ("圆周运动", None),
            ("抛体运动", None),
        ]),
        ("电磁学", None, [
            ("电场", None),
            ("电路", None),
            ("磁场", None),
            ("电磁感应", None),
            ("交变电流", None),
        ]),
        ("热学", None, [
            ("分子动理论", None),
            ("气体定律", None),
            ("热力学定律", None),
        ]),
        ("光学", None, [
            ("光的折射", None),
            ("光的干涉", None),
            ("光的衍射", None),
        ]),
        ("近代物理", None, [
            ("原子结构", None),
            ("核反应", None),
            ("光电效应", None),
        ]),
    ],
    "skill": [
        ("实验设计", None, []),
        ("数据分析", None, []),
        ("公式推导", None, []),
        ("图像分析", None, []),
    ],
    "error_type": [
        ("概念混淆", None, []),
        ("计算错误", None, []),
        ("审题不清", None, []),
        ("单位换算", None, []),
    ],
}


async def init_tags():
    await init_db()
    async with async_session_factory() as db:
        # Check if tags already exist
        from sqlalchemy import select, func
        result = await db.execute(select(func.count(Tag.id)))
        count = result.scalar()
        if count > 0:
            print(f"Tags already exist ({count} tags). Skipping init.")
            return

        created = 0
        for category, roots in PHYSICS_TAGS.items():
            for root_name, root_color, children in roots:
                parent = Tag(name=root_name, category=category, color=root_color)
                db.add(parent)
                await db.flush()
                created += 1

                for child_name, child_color in children:
                    child = Tag(name=child_name, category=category, color=child_color, parent_id=parent.id)
                    db.add(child)
                    created += 1

        await db.commit()
        print(f"Created {created} preset physics tags.")


if __name__ == "__main__":
    asyncio.run(init_tags())
