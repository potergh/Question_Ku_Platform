"""api_extract 暂存区四个端点的响应结构锁 + 审计闸门测试。

这份测试的作用是「冻结契约」：ExtractResponse / ExtractItemResponse 的字段集
一旦被改动（少字段、多字段、改名），这里立刻变红——前端预览页依赖同一份契约。

不需要真实 PDF：暂存区就是磁盘上的 extract.json，直接构造 ExtractResult 写盘，
再把 Source.ocr_result_path 指向同一目录即可复现识别完成后的状态。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from app.models import Job, Question, Source
from app.routers import extract as extract_router
from app.schemas.extract import ExtractItemResponse, ExtractResponse
from app.services.api_extract_adapter import (
    CHANNEL_API_EXTRACT,
    CHANNEL_LOCAL_OCR,
    CHANNEL_MINERU,
    EXTRACT_JSON_NAME,
    STAGING_STATUS,
    ExtractItemData,
    ExtractResult,
    write_extract_json,
)


def _item(qid: int = 1, **kwargs) -> ExtractItemData:
    """造一道暂存题目；card_image 必须是相对 document_dir 的路径。"""
    data: dict = {
        "qid": qid,
        "question_number": qid,
        "label": str(qid),
        "stem_md": f"第 {qid} 题题干",
        "content": f"第 {qid} 题题干",
        "raw_text": f"第 {qid} 题原文",
        "card_image": "questions/Q001.webp",
        "needs_review": False,
    }
    data.update(kwargs)
    return ExtractItemData(**data)


def _stage(
    tmp_path: Path, *, blocked: bool, items: list[ExtractItemData], **overrides
) -> tuple[Path, ExtractResult]:
    """把一份识别结果写进 ocr_output/doc1/extract.json，返回目录与结果对象。"""
    document_dir = tmp_path / "ocr_output" / "doc1"
    audit = overrides.pop(
        "audit", {"blocked": blocked, "coverage_ratio": 0.99, "reasons": []}
    )
    result = ExtractResult(
        output_dir=document_dir,
        items=items,
        audit=audit,
        document_name="doc1",
        **overrides,
    )
    write_extract_json(document_dir, result)
    return document_dir, result


async def _source(test_db, document_dir: Path, **overrides) -> str:
    """建一条指向暂存目录的 Source，返回其 id。"""
    data: dict = {
        "filename": "doc1.pdf",
        "file_path": "/tmp/doc1.pdf",
        "file_type": "pdf",
        "role": "paper",
        "extract_channel": CHANNEL_API_EXTRACT,
        "subject": "physics",
        "ocr_status": STAGING_STATUS,
        "ocr_result_path": str(document_dir),
    }
    data.update(overrides)
    async with test_db() as db:
        source = Source(**data)
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source.id


# ── GET：结构锁 ──────────────────────────────────────────────────────


async def test_get_extract_response_shape_is_locked(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1)])
    source_id = await _source(test_db, document_dir)

    resp = await client.get(f"/api/sources/{source_id}/extract")

    assert resp.status_code == 200
    body = resp.json()
    # 顶层与逐题字段集必须与 schema 完全一致（不多不少）
    assert set(body) == set(ExtractResponse.model_fields)
    assert set(body["items"][0]) == set(ExtractItemResponse.model_fields)
    # 题卡相对路径被翻成 HTTP URL：依赖路径里存在 'ocr_output' 片段
    assert (
        body["items"][0]["card_image_url"]
        == f"/api/ocr-assets/{source_id}/questions/Q001.webp"
    )
    assert body["items"][0]["changed_fields"] == []


# ── PUT：人工修订 ────────────────────────────────────────────────────


async def test_put_item_returns_diff_and_changed_fields(client, test_db, tmp_path):
    # 初始 needs_review=True：改完题干后它会被自动清掉，才能进 changed_fields
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1, needs_review=True)])
    source_id = await _source(test_db, document_dir)

    resp = await client.put(
        f"/api/sources/{source_id}/extract/items/1",
        json={"stem_md": "人工改写的题干"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"ok", "qid", "changed", "updated_at", "item"}
    assert body["changed"] == ["stem_md"]
    item = body["item"]
    # changed_fields 由 set 迭代得到，顺序不稳定，只比集合
    assert set(item["changed_fields"]) == {"stem_md", "needs_review"}
    assert item["needs_review"] is False

    # 修订已落盘：重新读取仍是新值
    again = await client.get(f"/api/sources/{source_id}/extract")
    assert again.json()["items"][0]["stem_md"] == "人工改写的题干"


async def test_put_unknown_qid_404(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1)])
    source_id = await _source(test_db, document_dir)

    resp = await client.put(
        f"/api/sources/{source_id}/extract/items/99", json={"stem_md": "x"}
    )

    assert resp.status_code == 404
    assert "qid=99" in resp.json()["detail"]


# ── confirm：审计闸门 ────────────────────────────────────────────────


async def test_confirm_blocked_returns_409(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=True, items=[_item(1)])
    source_id = await _source(test_db, document_dir)

    resp = await client.post(f"/api/sources/{source_id}/extract/confirm")

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["blocked"] is True
    assert detail["message"]
    assert "audit" in detail

    # 阻断时不入库
    async with test_db() as db:
        rows = (await db.execute(select(Question))).scalars().all()
    assert rows == []


async def test_confirm_force_bypasses_gate(client, test_db, tmp_path):
    items = [
        _item(1, needs_review=False),
        _item(2, needs_review=True),
        _item(3, excluded=True),
    ]
    document_dir, _ = _stage(tmp_path, blocked=True, items=items)
    source_id = await _source(test_db, document_dir)

    resp = await client.post(f"/api/sources/{source_id}/extract/confirm?force=true")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"ok", "confirmed", "question_count", "review_count", "forced"}
    assert body["question_count"] == 2  # 被剔除的第 3 题不入库
    assert body["review_count"] == 1
    assert body["forced"] is True

    async with test_db() as db:
        rows = (
            await db.execute(select(Question).where(Question.source_id == source_id))
        ).scalars().all()
        source = await db.get(Source, source_id)
    assert len(rows) == 2
    assert {row.review_status for row in rows} == {"approved", "pending"}
    assert source.ocr_status == "done"


async def test_confirm_then_preview_still_readable(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1, needs_review=False)])
    source_id = await _source(test_db, document_dir)

    confirm = await client.post(f"/api/sources/{source_id}/extract/confirm")
    assert confirm.status_code == 200

    resp = await client.get(f"/api/sources/{source_id}/extract")
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed"] is True
    assert body["ocr_status"] == "done"


# ── DELETE：丢弃暂存 ─────────────────────────────────────────────────


async def test_delete_discards_staging(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1)])
    source_id = await _source(test_db, document_dir)

    resp = await client.delete(f"/api/sources/{source_id}/extract")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"ok", "ocr_status", "channel"}
    assert body["ocr_status"] == "pending"
    assert body["channel"] == CHANNEL_API_EXTRACT
    assert not (document_dir / EXTRACT_JSON_NAME).exists()

    async with test_db() as db:
        source = await db.get(Source, source_id)
    assert source.question_count == 0
    assert source.review_count == 0


# ── rerun：守卫与正常路径 ────────────────────────────────────────────


async def test_rerun_guards(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1)])

    answer_id = await _source(test_db, document_dir, role="answer_doc")
    resp = await client.post(f"/api/sources/{answer_id}/extract/rerun")
    assert resp.status_code == 400
    assert "答案文档" in resp.json()["detail"]

    local_id = await _source(test_db, document_dir, extract_channel=CHANNEL_LOCAL_OCR)
    resp = await client.post(f"/api/sources/{local_id}/extract/rerun")
    assert resp.status_code == 400
    assert "本地 OCR" in resp.json()["detail"]

    missing_id = await _source(test_db, document_dir, file_path="")
    resp = await client.post(f"/api/sources/{missing_id}/extract/rerun")
    assert resp.status_code == 400
    assert "源文件缺失" in resp.json()["detail"]


async def test_rerun_happy_path(client, test_db, tmp_path, monkeypatch):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1)])
    source_id = await _source(test_db, document_dir)

    started: list[tuple] = []

    async def fake_process(*args, **kwargs):
        # 真实实现会去开 PDF；测试里只记录调用参数，避免误触文件系统。
        started.append(args)

    # 通道分发收进了 channels.runner_for，所以拦截点也跟着挪到这里。
    monkeypatch.setattr(extract_router, "runner_for", lambda channel: fake_process)

    resp = await client.post(f"/api/sources/{source_id}/extract/rerun")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"ok", "job_id", "channel"}
    assert body["channel"] == CHANNEL_API_EXTRACT
    assert body["job_id"]
    # 旧暂存被丢弃，状态回到 processing
    assert not (document_dir / EXTRACT_JSON_NAME).exists()
    async with test_db() as db:
        source = await db.get(Source, source_id)
    assert source.ocr_status == "processing"
    assert source.question_count == 0
    assert source.review_count == 0

    await asyncio.sleep(0)  # 让 create_task 排进来的协程跑完
    assert started and started[0][0] == source_id


async def test_rerun_supports_mineru_channel(client, test_db, tmp_path, monkeypatch):
    """暂存通道不止 api_extract：MinerU 的暂存区也要能重跑，且跑回自己的通道。

    这条盯的是一个真踩过的坑：rerun 以前写死 `!= CHANNEL_API_EXTRACT` 就拒绝，
    加通道时表现为「预览能打开、点重跑报 400」，报错信息完全指不到根因。
    """
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1)])
    source_id = await _source(test_db, document_dir, extract_channel=CHANNEL_MINERU)

    started: list[tuple] = []
    asked_channels: list[str] = []

    async def fake_process(*args, **kwargs):
        started.append(args)

    def fake_runner_for(channel):
        asked_channels.append(channel)
        return fake_process

    monkeypatch.setattr(extract_router, "runner_for", fake_runner_for)

    resp = await client.post(f"/api/sources/{source_id}/extract/rerun")
    assert resp.status_code == 200
    assert resp.json()["channel"] == CHANNEL_MINERU

    await asyncio.sleep(0)
    assert asked_channels == [CHANNEL_MINERU]
    assert started and started[0][0] == source_id

    # Job.job_type 也要跟着通道走，否则任务列表里认不出这是 MinerU 的任务
    async with test_db() as db:
        job = (await db.execute(select(Job))).scalars().one()
    assert job.job_type == CHANNEL_MINERU


# ── 404 分支 ─────────────────────────────────────────────────────────


async def test_load_staged_404_branches(client, test_db, tmp_path):
    # 1) source 不存在
    resp = await client.get("/api/sources/nope/extract")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Source not found"

    # 2) 还没有识别结果（ocr_result_path 为空）
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1)])
    no_path_id = await _source(test_db, document_dir, ocr_result_path=None)
    resp = await client.get(f"/api/sources/{no_path_id}/extract")
    assert resp.status_code == 404
    assert "还没有识别结果" in resp.json()["detail"]

    # 3) 目录里没有 extract.json
    empty_dir = tmp_path / "ocr_output" / "empty"
    missing_id = await _source(test_db, empty_dir)
    resp = await client.get(f"/api/sources/{missing_id}/extract")
    assert resp.status_code == 404
    assert "存在或已损坏" in resp.json()["detail"]


# ── 答案图落库 ───────────────────────────────────────────────────────


async def test_confirm_persists_answer_images(client, test_db, tmp_path):
    """答案是图的题（卷面只写「如上图所示」）要把答案图带进题库接口。"""
    document_dir, _ = _stage(
        tmp_path,
        blocked=False,
        items=[
            _item(
                1,
                needs_review=False,
                answer_figures=["figures/answer_Q001_01.webp"],
            )
        ],
    )
    source_id = await _source(test_db, document_dir)

    confirm = await client.post(f"/api/sources/{source_id}/extract/confirm")
    assert confirm.status_code == 200

    async with test_db() as db:
        question = (await db.execute(select(Question))).scalars().one()
    # 落库存绝对路径，与 card_image_path 一致
    assert question.answer_image_paths == [
        str(document_dir / "figures/answer_Q001_01.webp")
    ]

    # 出参转成可直接访问的 HTTP URL
    listing = await client.get(f"/api/questions?source_id={source_id}")
    assert listing.status_code == 200
    assert listing.json()["questions"][0]["answer_image_paths"] == [
        f"/api/ocr-assets/{source_id}/figures/answer_Q001_01.webp"
    ]


async def test_confirm_without_answer_images_persists_empty_list(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1, needs_review=False)])
    source_id = await _source(test_db, document_dir)

    assert (await client.post(f"/api/sources/{source_id}/extract/confirm")).status_code == 200

    listing = await client.get(f"/api/questions?source_id={source_id}")
    assert listing.json()["questions"][0]["answer_image_paths"] == []


# ── 答案图落库 ───────────────────────────────────────────────────────


async def test_confirm_persists_answer_images(client, test_db, tmp_path):
    """答案是图的题（卷面只写「如上图所示」）要把答案图带进题库接口。"""
    document_dir, _ = _stage(
        tmp_path,
        blocked=False,
        items=[
            _item(
                1,
                needs_review=False,
                answer_figures=["figures/answer_Q001_01.webp"],
            )
        ],
    )
    source_id = await _source(test_db, document_dir)

    confirm = await client.post(f"/api/sources/{source_id}/extract/confirm")
    assert confirm.status_code == 200

    async with test_db() as db:
        question = (await db.execute(select(Question))).scalars().one()
    # 落库存绝对路径，与 card_image_path 一致
    assert question.answer_image_paths == [
        str(document_dir / "figures/answer_Q001_01.webp")
    ]

    # 出参转成可直接访问的 HTTP URL
    listing = await client.get(f"/api/questions?source_id={source_id}")
    assert listing.status_code == 200
    assert listing.json()["questions"][0]["answer_image_paths"] == [
        f"/api/ocr-assets/{source_id}/figures/answer_Q001_01.webp"
    ]


async def test_confirm_without_answer_images_persists_empty_list(client, test_db, tmp_path):
    document_dir, _ = _stage(tmp_path, blocked=False, items=[_item(1, needs_review=False)])
    source_id = await _source(test_db, document_dir)

    assert (await client.post(f"/api/sources/{source_id}/extract/confirm")).status_code == 200

    listing = await client.get(f"/api/questions?source_id={source_id}")
    assert listing.json()["questions"][0]["answer_image_paths"] == []
