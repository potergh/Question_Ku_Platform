"""阶段 0 Task 0.2：构建基线练习样本（真实题库选题，固定名称，可重复运行）。

为每个学科建一份代表性基线练习，并导出 PDF / Word / 分页预览 PNG：
- 基线-物理-主：文字+单图+多图+混合题型+三页以上（主回归基线）
- 基线-数学-代表：复杂内容优先（公式题、综合题）
- 基线-化学-代表：实验题、方程式文本、图
- 基线-英语-代表：长文本、题组

每份样本：标题/副标题/信息栏/分值/留白/分页全覆盖。
输出目录：data/baselines/（固定文件名，供后续阶段回归对比）
幂等：同标题练习已存在则复用（不重复建），文件直接覆盖重新导出。
"""

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import Question  # noqa: E402
from app.models.practice import Practice, PracticeQuestion, PracticeSection  # noqa: E402
from app.services import practice_service, render_service, docx_export, preview_service, block_service  # noqa: E402
from app.routers.practices import _get_practice_full  # noqa: E402

BASELINE_DIR = settings.data_dir / "baselines"

FORMULA_KEYS = ("$(", "$$", "\\(", "\\[")

# 分值默认表（仅基线样本使用，覆盖"分值"展示）
SCORE_BY_TYPE = {"single_choice": 3, "multiple_choice": 4, "fill_blank": 4,
                 "comprehensive": 10, "experiment": 10, "unknown": 2}
# 需要设置小节分页的题型（存的是中文题型名；覆盖“分页”展示）
NEW_PAGE_TYPES = {"综合题", "实验题", "解答题"}


def _feat_rank(q: Question) -> tuple:
    """选题排序权重：公式 > 多图 > 单图 > 长文本。"""
    c = q.content or ""
    imgs = c.count("asset://") + c.count("/api/practices/")
    return (
        -int(any(k in c for k in FORMULA_KEYS)),
        -min(imgs, 2),
        -len(c),
    )


async def _pick(db, subject: str, types: dict[str, int], taken: set) -> list:
    """按题型配额选题，特征丰富者优先，避免跨练习重复使用同一题。"""
    picked = []
    for qtype, quota in types.items():
        rows = (await db.execute(
            select(Question).where(Question.subject == subject,
                                   Question.question_type == qtype,
                                   Question.is_deleted == False)  # noqa: E712
        )).scalars().all()
        rows = sorted((q for q in rows if q.id not in taken), key=_feat_rank)
        picked.extend(rows[:quota])
        taken.update(q.id for q in rows[:quota])
    return picked


async def _set_scores_and_pages(db, practice: Practice):
    """基线样本统一补分值；综合/实验小节分页；开启信息栏与总分；打基线标记。"""
    practice.is_baseline = True   # 列表中标记为基线样本（用户决策 2026-08-30）
    for sec in practice.sections:
        if sec.section_type in NEW_PAGE_TYPES and sec.position > 0:
            sec.start_on_new_page = True
        for pq in sec.questions:
            if pq.score is None:
                pq.score = SCORE_BY_TYPE.get(pq.question_type, 2)
    practice.page_config = {**(practice.page_config or {}),
                            "show_info_bar": True, "show_total_score": True,
                            "show_page_number": True, "show_score": True}


async def _delete_one(db, name: str):
    """删除同名基线练习及其资产/预览目录（--rebuild 用）。"""
    existing = (await db.execute(
        select(Practice).where(Practice.title == name))).scalar_one_or_none()
    if not existing:
        return
    pid = existing.id
    await db.delete(existing)
    await db.commit()
    d = settings.data_dir / "practices" / pid
    if d.exists():
        shutil.rmtree(d)
    print(f"  [删除] {name} ({pid})")


async def _build_one(db, name: str, subtitle: str, subject: str,
                     types: dict[str, int], taken: set) -> Practice:
    existing = (await db.execute(
        select(Practice).where(Practice.title == name))).scalar_one_or_none()
    if existing:
        print(f"  [复用] {name}（已存在，跳过重建）")
        full = await _get_practice_full(db, existing.id)
        await _set_scores_and_pages(db, full)   # 幂等：每次运行都保证配置到位
        await db.commit()
        return full

    questions = await _pick(db, subject, types, taken)
    if not questions:
        raise RuntimeError(f"{name} 未选到任何题目")
    practice = await practice_service.create_practice_from_questions(
        db, name, subtitle, subject, None, questions)
    await db.commit()
    # 重新加载完整关系后再补分值/分页（避免未加载的关系）
    full = await _get_practice_full(db, practice.id)
    await _set_scores_and_pages(db, full)
    await db.commit()
    return full


async def _export_one(db: AsyncSession, practice: Practice, slug: str) -> dict:
    """渲染预览并导出 PDF / Word / 分页 PNG 到基线目录（与线上导出同一管线）。"""
    full = await _get_practice_full(db, practice.id)
    changed = False
    for sec in full.sections:
        for pq in sec.questions:
            if not pq.blocks:
                await block_service.materialize_blocks(db, pq)
                changed = True
    if changed:
        await db.commit()
        full = await _get_practice_full(db, practice.id)
    html = render_service.build_practice_html(full, practice.id)
    rs = render_service.render_settings(full)
    pdf_path, sha, pages = await render_service.ensure_preview_pdf(practice.id, html, rs)

    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_out = BASELINE_DIR / f"baseline_{slug}.pdf"
    pdf_out.write_bytes(pdf_path.read_bytes())
    docx_out = BASELINE_DIR / f"baseline_{slug}.docx"
    docx_out.write_bytes(await asyncio.to_thread(docx_export.build_docx, full, practice.id))
    pngs = []
    for i in range(1, pages + 1):
        png = preview_service.page_png(pdf_path, i, 1.5)
        p = BASELINE_DIR / f"baseline_{slug}_page{i:02d}.png"
        p.write_bytes(png)
        pngs.append(p.name)
    return {"id": practice.id, "pages": pages, "sha": sha,
            "pdf": pdf_out.name, "docx": docx_out.name, "pngs": pngs}


SPEC = [
    # 物理主基线：13 题、四种题型，目标三页以上
    ("基线-物理-主", "阶段0基线样本（物理）", "physics", "physics_main",
     {"single_choice": 4, "multiple_choice": 2, "fill_blank": 3, "comprehensive": 4}),
    # 数学代表：公式与综合题优先
    ("基线-数学-代表", "阶段0基线样本（数学）", "math", "math_rep",
     {"single_choice": 3, "fill_blank": 2, "comprehensive": 3}),
    # 化学代表：含实验题
    ("基线-化学-代表", "阶段0基线样本（化学）", "chemistry", "chemistry_rep",
     {"single_choice": 3, "fill_blank": 2, "comprehensive": 2, "experiment": 2}),
    # 英语代表：长文本、题组
    ("基线-英语-代表", "阶段0基线样本（英语）", "english", "english_rep",
     {"single_choice": 4, "unknown": 4}),
]


async def main(rebuild: bool = False):
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = {"practices": []}
    taken: set = set()
    # 清理旧导出（页数变化时避免残留多余分页 PNG）
    if BASELINE_DIR.exists():
        for f in BASELINE_DIR.glob("baseline_*"):
            f.unlink()
    async with async_session_factory() as db:
        if rebuild:
            print("--rebuild：先删除旧基线练习再重建")
            for name, *_ in SPEC:
                await _delete_one(db, name)
        for name, subtitle, subject, slug, types in SPEC:
            print(f"构建 {name} …")
            practice = await _build_one(db, name, subtitle, subject, types, taken)
            info = await _export_one(db, practice, slug)
            n_q = sum(len(s.questions) for s in practice.sections)
            manifest["practices"].append({
                "name": name, "subject": subject, "questions": n_q, **info})
            print(f"  [完成] {name}：{n_q} 题，{info['pages']} 页 → {BASELINE_DIR}")

    out = BACKEND_DIR / "scripts" / "reports" / "phase0_baseline_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"清单: {out}")
    over3 = [p["name"] for p in manifest["practices"] if p["pages"] >= 3]
    print("达到三页以上的样本:", over3 or "（无，需要加题）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true",
                        help="删除同名旧基线练习与资产目录后重建")
    args = parser.parse_args()
    asyncio.run(main(rebuild=args.rebuild))
