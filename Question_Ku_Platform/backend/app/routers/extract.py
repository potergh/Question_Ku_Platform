"""Extract router — api_extract 通道的暂存区（预览 / 逐题编辑 / 确认入库 / 重跑 / 丢弃）。

暂存区是磁盘上的 extract.json，不建新表：一份文档一次识别对应一个 JSON，
生命周期跟着 `ocr_output/<doc>/` 走（delete_source 已对该目录整体 rmtree）。

确认入库是全局唯一把 ExtractItemData 变成 Question 的地方，字段映射与
`ocr_service.py` 完全一致（同一套 QuestionData 契约），因此复核流、组卷、
资产服务、统计全部零改动复用。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Job, Question, Source
from app.schemas.extract import ExtractItemPatch, ExtractItemResponse, ExtractResponse
from app.services.api_extract_adapter import (
    CHANNEL_LOCAL_OCR,
    EXTRACT_JSON_NAME,
    STAGED_CHANNELS,
    STAGING_STATUS,
    ExtractItemData,
    ExtractResult,
    apply_item_patch,
    read_extract_json,
    write_extract_json,
)
from app.services.channels import job_type_for, runner_for
from app.services.question_builder import build_question
from app.utils.assets import resolve_asset_urls, resolve_card_image_path
from app.utils.question_types import normalize_question_type
from app.utils.warnings import split_warnings

logger = logging.getLogger(__name__)

router = APIRouter()

# 可预览的状态：staging 是新建的暂存态；done 表示已确认但暂存文件仍在，
# 允许回看与二次修订（confirm 幂等，会替换已有题目）。
PREVIEWABLE_STATUS = {STAGING_STATUS, "done"}


# ── helpers ─────────────────────────────────────────────────────────


async def _load_staged(
    db: AsyncSession, source_id: str
) -> tuple[Source, Path, ExtractResult]:
    """取 source 与其暂存结果；三者缺一不可，缺失即 404 并说明补救方式。"""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if not source.ocr_result_path:
        raise HTTPException(404, "该文档还没有识别结果，请先上传并等待识别完成")

    document_dir = Path(source.ocr_result_path)
    result = read_extract_json(document_dir)
    if result is None:
        raise HTTPException(
            404,
            f"暂存结果不存在或已损坏（{EXTRACT_JSON_NAME}），请在文档列表里重跑识别",
        )
    return source, document_dir, result


def _changed_fields(item: ExtractItemData) -> list[str]:
    """相对首次快照被人工改过的字段，供前端高亮。"""
    if not item.original:
        return []
    return [key for key, value in item.original.items() if getattr(item, key, None) != value]


def _serialize_item(
    item: ExtractItemData, document_dir: Path, source_id: str
) -> ExtractItemResponse:
    """把磁盘相对路径翻成 HTTP URL。

    暂存 JSON 里存的是相对路径（可迁移），前端只认 `/api/ocr-assets/...`；
    正文中的 `asset://` 内联插图同样要转换，否则预览页图片全裂。
    """
    payload = item.to_dict()
    # 英语篇章题：按板块归一题型，让已 staging 的旧数据不重跑也能在预览页显示正确题型。
    payload["question_type"] = normalize_question_type(item.question_type, item.section)
    payload.pop("card_image", None)
    payload.pop("figures", None)
    payload.pop("answer_figures", None)

    card_abs = str(document_dir / item.card_image) if item.card_image else None
    payload["card_image_url"] = resolve_card_image_path(card_abs, source_id)
    payload["figure_urls"] = [
        f"/api/ocr-assets/{source_id}/{Path(figure).as_posix()}" for figure in item.figures
    ]
    payload["answer_figure_urls"] = [
        f"/api/ocr-assets/{source_id}/{Path(figure).as_posix()}"
        for figure in item.answer_figures
    ]
    # 答案是题干图本身的题：标注指向题干哪张图（带可点开的 URL），不重复裁图。
    payload["answer_figure_refs"] = [
        {
            **ref,
            "stem_figure_url": (
                f"/api/ocr-assets/{source_id}/"
                f"{Path(str(ref['stem_figure'])).as_posix()}"
            ),
        }
        for ref in item.answer_figure_refs
        if ref.get("stem_figure")
    ]
    # 多小问答案的分块：figures 是相对路径，给前端补一份可直接预览的 URL。
    payload["answer_blocks"] = [
        {
            **block,
            "figure_urls": [
                f"/api/ocr-assets/{source_id}/{Path(figure).as_posix()}"
                for figure in block.get("figures", [])
            ],
        }
        for block in item.answer_blocks
    ]
    for name in ("stem_md", "content", "answer", "explanation"):
        value = payload.get(name)
        if value:
            payload[name] = resolve_asset_urls(value, source_id)
    # 选项里的内联插图同样是 asset://（四图选择题的图就写在选项里）。
    # 漏掉这一层，复核页选项只剩 alt 文本、图片全裂。
    payload["options"] = [
        {**opt, "content": resolve_asset_urls(opt.get("content"), source_id)}
        if isinstance(opt, dict)
        else opt
        for opt in (payload.get("options") or [])
    ]
    payload["changed_fields"] = _changed_fields(item)
    return ExtractItemResponse(**payload)


def _serialize(source: Source, result: ExtractResult, document_dir: Path) -> ExtractResponse:
    # 警告分级：带内部行号/术语的是写给写管线的人看的，不进用户可见的警告条。
    user_warnings, diagnostics = split_warnings(result.warnings)
    return ExtractResponse(
        source_id=source.id,
        filename=source.filename,
        document_name=result.document_name,
        doc_kind=result.doc_kind,
        channel=result.channel,
        schema_version=result.schema_version,
        ocr_status=source.ocr_status,
        confirmed=result.confirmed,
        created_at=result.created_at,
        updated_at=result.updated_at,
        question_count=result.question_count,
        review_count=result.review_count,
        excluded_count=sum(1 for item in result.items if item.excluded),
        audit=result.audit,
        blocked=result.blocked,
        qa=result.qa,
        answer_report=result.answer_report,
        non_question_regions=result.non_question_regions,
        warnings=user_warnings,
        diagnostics=diagnostics,
        usage=result.usage,
        timings=result.timings,
        items=[_serialize_item(item, document_dir, source.id) for item in result.items],
    )


def _sync_counts(source: Source, result: ExtractResult) -> None:
    """暂存期就把题目数写回 source：列表页可直接显示「待确认 N 题」。"""
    source.question_count = result.question_count
    source.review_count = result.review_count


async def _last_payload(db: AsyncSession, source_id: str) -> str | None:
    """沿用上一条任务的 payload（doc_kind、配对信息），重跑时不丢提示。"""
    found = await db.execute(
        select(Job)
        .where(Job.source_id == source_id)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    previous = found.scalar_one_or_none()
    return previous.payload if previous and previous.payload else None


# ── 端点 ────────────────────────────────────────────────────────────


@router.get("/api/sources/{source_id}/extract", response_model=ExtractResponse)
async def get_extract(source_id: str, db: AsyncSession = Depends(get_db)):
    """读暂存结果：逐题结构化内容 + 题卡图 URL + 审计摘要 + 三源答案对照。"""
    source, document_dir, result = await _load_staged(db, source_id)
    return _serialize(source, result, document_dir)


@router.put("/api/sources/{source_id}/extract/items/{qid}")
async def update_extract_item(
    source_id: str,
    qid: int,
    patch: ExtractItemPatch,
    db: AsyncSession = Depends(get_db),
):
    """保存单题人工修改，写回 extract.json 并保留 original 快照。"""
    source, document_dir, result = await _load_staged(db, source_id)
    item = next((row for row in result.items if row.qid == qid), None)
    if item is None:
        raise HTTPException(404, f"暂存区里没有 qid={qid} 的题目")

    changed = apply_item_patch(item, patch.model_dump(exclude_unset=True))
    write_extract_json(document_dir, result)
    if source.ocr_status == STAGING_STATUS:
        _sync_counts(source, result)
    await db.commit()

    return {
        "ok": True,
        "qid": qid,
        "changed": changed,
        # 用 updated_at 做乐观并发/刷新判据，避免前端缓存旧值。
        "updated_at": result.updated_at,
        "item": _serialize_item(item, document_dir, source_id),
    }


@router.post("/api/sources/{source_id}/extract/confirm")
async def confirm_extract(
    source_id: str,
    force: bool = Query(default=False, description="审计不通过时强制入库"),
    db: AsyncSession = Depends(get_db),
):
    """幂等入库：先清掉该 source 已有题目，再按暂存结果重建。

    `audit.blocked` 为真（覆盖率低于闸门 / 有孤儿页）时返回 409，
    除非显式 `force=true` —— 编造或漏题的代价高于晚一点入库。
    """
    source, document_dir, result = await _load_staged(db, source_id)

    if result.blocked and not force:
        raise HTTPException(
            409,
            detail={
                "message": "覆盖率审计未通过，确认入库可能丢失题目",
                "blocked": True,
                "audit": result.audit,
            },
        )

    kept = [item for item in result.items if not item.excluded]
    if not kept:
        raise HTTPException(400, "暂存结果里没有可入库的题目（全部被剔除或识别为空）")

    # 幂等：软删除旧题目，保留历史且与 delete_question 语义一致。
    existing = await db.execute(
        select(Question).where(
            Question.source_id == source_id, Question.is_deleted == False  # noqa: E712
        )
    )
    now = datetime.now()
    for question in existing.scalars().all():
        question.is_deleted = True
        question.deleted_at = now

    created = 0
    for item in kept:
        qd = item.to_question_data(document_dir)
        db.add(build_question(qd, source_id=source_id, subject=source.subject))
        created += 1

    result.confirmed = True
    write_extract_json(document_dir, result)

    source.ocr_status = "done"
    source.ocr_result_path = str(document_dir)
    source.question_count = created
    source.review_count = result.review_count
    await db.commit()

    logger.info(
        "extract confirmed source=%s：入库 %d 题（待复核 %d），force=%s",
        source_id, created, result.review_count, force,
    )
    return {
        "ok": True,
        "confirmed": True,
        "question_count": created,
        "review_count": result.review_count,
        "forced": force,
    }


@router.post("/api/sources/{source_id}/extract/rerun")
async def rerun_extract(source_id: str, db: AsyncSession = Depends(get_db)):
    """丢弃暂存并重跑识别（沿用原通道与上一条任务的 payload）。"""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if source.role == "answer_doc":
        raise HTTPException(400, "答案文档不单独重跑，请重跑与其配对的试卷")
    channel = source.extract_channel or CHANNEL_LOCAL_OCR
    if channel not in STAGED_CHANNELS:
        raise HTTPException(400, "该文档走本地 OCR 通道，没有暂存区可重跑")
    if not source.file_path:
        raise HTTPException(400, "源文件缺失，无法重跑")

    payload = await _last_payload(db, source.id)

    # 丢弃旧暂存：状态立刻变 processing，预览页据此显示「识别中」。
    if source.ocr_result_path:
        (Path(source.ocr_result_path) / EXTRACT_JSON_NAME).unlink(missing_ok=True)

    source.ocr_status = "processing"
    source.question_count = 0
    source.review_count = 0

    job = Job(
        job_type=job_type_for(channel),
        source_id=source.id,
        status="queued",
        payload=payload,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    asyncio.create_task(runner_for(channel)(source.id, source.file_path, job.id))
    return {"ok": True, "job_id": job.id, "channel": channel}


@router.delete("/api/sources/{source_id}/extract")
async def discard_extract(source_id: str, db: AsyncSession = Depends(get_db)):
    """丢弃暂存结果。已确认入库（done）时只删暂存文件，不动题库里的题目。"""
    source = await db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    if source.ocr_result_path:
        (Path(source.ocr_result_path) / EXTRACT_JSON_NAME).unlink(missing_ok=True)

    if source.ocr_status == STAGING_STATUS:
        # 回到 pending：文档列表里可以重新触发识别。
        source.ocr_status = "pending"
        source.question_count = 0
        source.review_count = 0
    await db.commit()

    return {"ok": True, "ocr_status": source.ocr_status, "channel": source.extract_channel}
