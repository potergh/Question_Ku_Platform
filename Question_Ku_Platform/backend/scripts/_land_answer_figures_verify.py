"""把 v9 回归产物按真实入库流程落到本地库，验证答案区插图端到端可达。

零模型成本：产物已经躺在磁盘上，这里只跑「暂存读取 → 确认入库 → 题库出参 → 图片下载」。

做四件事（幂等，可反复跑）：
1. 把 `...__v9` 回归快照复制成 `...__v9landing`：confirm 会把 `confirmed=true`
   写回产物目录，不能让回归快照被改脏；
2. 在库里建/更新一条 source 指向该目录（api_extract 通道、staging 态）；
3. 走 HTTP 接口：GET extract → POST confirm → GET questions，
   断言 `answer_figure_urls` / `answer_image_paths` 三题齐全；
4. 真下载一张答案图，确认 `/api/ocr-assets` 能把它读出来。

用法：
    python -m scripts._land_answer_figures_verify
    python -m scripts._land_answer_figures_verify --clean   # 顺带清掉落库数据与副本
"""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Question, Source  # noqa: E402

PDF_NAME = "2022年天津市和平区中考物理一模试卷.pdf"
SNAPSHOT_DIRNAME = "2022年天津市和平区中考物理一模试卷__v9"
LANDING_DIRNAME = "2022年天津市和平区中考物理一模试卷__v9landing"

# 卷面答案是图的题：label → 期望张数。
# 2026-09-12 起答案区重印题干图的排重生效，数字比「排除重印前」各少 1-2 张：
# 旧值 20→3 / 24→4 / 26→2，现在 2 / 2 / 1。
# 第 20 题答案区（【答案】标记旁）只有一张 R1/R2 电路图；【解答】里的
# "图甲/图乙/图丙"是推导图，答案区优先口径下不再抓（2026-09-12 用户拍板）。
EXPECTED_ANSWER_FIGURES = {"20．": 1, "24．": 2, "26．": 1}


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def stage_snapshot() -> Path:
    """复制回归快照为落库专用目录，返回该目录。"""
    src = settings.ocr_output_dir / SNAPSHOT_DIRNAME
    if not src.exists():
        _fail(f"回归快照不存在：{src}")
    dst = settings.ocr_output_dir / LANDING_DIRNAME
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    _ok(f"产物副本就位：{dst.name}（{sum(1 for _ in dst.rglob('*'))} 项）")
    return dst


async def ensure_source(landing_dir: Path) -> str:
    """建/更新 source，返回 source_id。"""
    async with async_session_factory() as db:
        source = (
            await db.execute(select(Source).where(Source.filename == PDF_NAME))
        ).scalar_one_or_none()
        if source is None:
            source = Source(id=uuid.uuid4().hex, filename=PDF_NAME)
            db.add(source)
            created = True
        else:
            created = False
        source.file_path = str(BACKEND_DIR.parent / "test_data" / PDF_NAME)
        source.file_type = "pdf"
        source.role = "paper"
        source.subject = "物理"
        source.extract_channel = "api_extract"
        # staging：暂存态才允许走 confirm（confirm 做完会改写成 done）
        source.ocr_status = "staging"
        source.ocr_result_path = str(landing_dir)
        await db.commit()
        _ok(f"source {'新建' if created else '复用并重置'}  id={source.id}")
        return source.id


async def main() -> None:
    client_kwargs = {"base_url": "http://verify"}
    transport = httpx.ASGITransport(app=app)

    landing_dir = stage_snapshot()
    source_id = await ensure_source(landing_dir)

    async with httpx.AsyncClient(transport=transport, **client_kwargs) as client:
        # ── 1. 暂存读取 ────────────────────────────────────────────
        resp = await client.get(f"/api/sources/{source_id}/extract")
        if resp.status_code != 200:
            _fail(f"GET extract → {resp.status_code} {resp.text[:300]}")
        staged = resp.json()
        items = staged["items"]
        _ok(f"暂存读取：{len(items)} 题，blocked={staged.get('blocked')}")

        staged_figures: dict[str, list[str]] = {}
        for item in items:
            urls = item.get("answer_figure_urls") or []
            if urls:
                staged_figures[item["label"]] = urls
        for label, want in EXPECTED_ANSWER_FIGURES.items():
            got = staged_figures.get(label, [])
            if len(got) != want:
                _fail(f"暂存区 {label} 答案图 {len(got)} 张，期望 {want} 张")
            _ok(f"{label} 答案图 {len(got)} 张 → {got[0]}")

        # ── 2. 确认入库 ────────────────────────────────────────────
        resp = await client.post(f"/api/sources/{source_id}/extract/confirm")
        if resp.status_code != 200:
            _fail(f"POST confirm → {resp.status_code} {resp.text[:300]}")
        confirmed = resp.json()
        _ok(f"入库：{confirmed['question_count']} 题（待复核 {confirmed['review_count']}）")

        # ── 3. 题库出参 ────────────────────────────────────────────
        resp = await client.get("/api/questions", params={"source_id": source_id, "page_size": 100})
        if resp.status_code != 200:
            _fail(f"GET questions → {resp.status_code} {resp.text[:300]}")
        listed = resp.json()["questions"]
        _ok(f"题库接口按 source 过滤出 {resp.json()['total']} 题")
        by_label = {str(q["question_number"]).strip().rstrip("．."): q for q in listed}
        for label, want in EXPECTED_ANSWER_FIGURES.items():
            text = label.rstrip("．")
            row = by_label.get(text)
            if row is None:
                _fail(f"题库出参里找不到第 {text} 题（已有题号：{sorted(by_label)}）")
            paths = row.get("answer_image_paths") or []
            if len(paths) != want:
                _fail(f"题库 {text} 题 answer_image_paths {len(paths)} 条，期望 {want} 条：{paths}")
            bad = [p for p in paths if not str(p).startswith("/api/ocr-assets/")]
            if bad:
                _fail(f"题库 {text} 题有未转成 URL 的路径：{bad}")
            _ok(f"{text} 题落库 {len(paths)} 条，出参已是 URL：{paths[0]}")

        # ── 4. 图片真下载 ──────────────────────────────────────────
        target = by_label["20"]["answer_image_paths"][0]
        resp = await client.get(target)
        if resp.status_code != 200:
            _fail(f"下载答案图 {target} → {resp.status_code}")
        if len(resp.content) < 1024:
            _fail(f"答案图内容可疑，仅 {len(resp.content)} 字节")
        _ok(f"答案图可下载：{target} → {resp.status_code} {len(resp.content) // 1024} KB")

    # ── 5. 直接查库兜底（不信接口自证） ────────────────────────────
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(Question).where(
                    Question.source_id == source_id, Question.is_deleted == False  # noqa: E712
                )
            )
        ).scalars().all()
        with_figs = [q for q in rows if q.answer_image_paths]
        total = sum(len(q.answer_image_paths or []) for q in rows)
        if len(with_figs) != len(EXPECTED_ANSWER_FIGURES):
            _fail(f"库里带答案图的题 {len(with_figs)} 道，期望 {len(EXPECTED_ANSWER_FIGURES)} 道")
        _ok(f"库里共 {len(rows)} 题，其中 {len(with_figs)} 道带答案图，合计 {total} 张")
        for q in with_figs:
            exists = [Path(p).exists() for p in q.answer_image_paths]
            if not all(exists):
                _fail(f"第 {q.question_number} 题有落库路径指向不存在的文件：{q.answer_image_paths}")
        _ok("所有落库路径都能对应到磁盘文件")

    print("\n=== 落库链路验证全部通过 ===")


async def clean() -> None:
    async with async_session_factory() as db:
        source = (
            await db.execute(select(Source).where(Source.filename == PDF_NAME))
        ).scalar_one_or_none()
        if source:
            for q in (
                await db.execute(select(Question).where(Question.source_id == source.id))
            ).scalars().all():
                await db.delete(q)
            await db.delete(source)
            await db.commit()
            _ok(f"已从库里清掉 source={source.id} 及其题目")
        else:
            _ok("库里没有和平卷 source，无需清理")
    dst = settings.ocr_output_dir / LANDING_DIRNAME
    if dst.exists():
        shutil.rmtree(dst)
        _ok(f"已删除产物副本 {dst.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="只清理落库数据与产物副本")
    args = parser.parse_args()
    import asyncio

    asyncio.run(clean() if args.clean else main())
