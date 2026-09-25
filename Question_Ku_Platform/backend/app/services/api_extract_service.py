"""api_extract 通道的 Job / Source 生命周期 —— 镜像 ocr_service，止步于暂存区。

与 ocr_service.process_pdf_async 唯一的差别：跑完**不写 Question**，只把 Source
置为 staging，等用户在预览页确认后由 routers/extract.py 幂等入库。

本模块负责三件 ocr_service 没有的事：
1. 从 Job.payload 读通道参数（文档形态提示等），坏 JSON 只当没传；
2. 配对答案文档在 upload 阶段不单独建 Job，由试卷任务顺手跑一遍同一条管线，
   取它的 items[] 当第三答案源（跑不出来只是少一个答案源，不阻断试卷）；
3. 把 run_extract 内部 5..95 的进度线性映射到 Job 的进度区间并落库。

Job/Source 的置位与收尾复用 `recognition_lifecycle`，与 ocr_service 同源。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.database import async_session_factory
from app.models import Job, Source
from app.services.api_extract import ExtractCancelled
from app.services.api_extract.service import run_extract
from app.services.api_extract.usage import track_usage
from app.services.api_extract.vlm_client import VLMConfigError, get_vision_config
from app.services.api_extract_adapter import (
    CHANNEL_API_EXTRACT,
    EXTRACT_JSON_NAME,
    STAGING_STATUS,
    ExtractResult,
)
from app.services.recognition_lifecycle import (
    finish_cancelled,
    finish_failed,
    finish_success,
    get_job,
    is_cancelled,
    map_progress_band,
    mark_running,
    parse_job_payload,
)
from app.utils.pdf_watermark import prepare_pdf

logger = logging.getLogger(__name__)

# 进度区间：配对答案文档先跑，占前一段；主文档占后一段。
COMPANION_BAND = (5.0, 25.0)
MAIN_BAND = (25.0, 95.0)


async def _ensure_companion_extract(
    db,
    source: Source,
    config: dict,
    *,
    progress,
    cancel_check,
) -> Path | None:
    """确保配对答案文档也有暂存结果，返回它的 extract.json 路径。

    upload 阶段不为 answer_doc 建识别 Job（暂存区设计如此），所以由试卷任务
    顺手跑一遍同一条管线拿 items[] 当第三答案源。答案文档本身也标 done，
    这样它的图片资产 URL 与来源列表都正常。
    """
    if not source.companion_source_id:
        return None

    companion = await db.get(Source, source.companion_source_id)
    if companion is None or not companion.file_path:
        logger.warning("source %s 的配对答案文档不存在，跳过第三答案源", source.id)
        return None

    document_dir = settings.ocr_output_dir / Path(companion.file_path).stem
    target = document_dir / EXTRACT_JSON_NAME
    if target.exists():
        return target

    try:
        result = await run_extract(
            config,
            Path(companion.file_path),
            settings.ocr_output_dir,
            subject=companion.subject or source.subject,
            source_id=companion.id,
            progress=map_progress_band(progress, *COMPANION_BAND, prefix="答案文档："),
            cancel_check=cancel_check,
        )
    except ExtractCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 — 第三答案源失败不阻断主流程
        logger.warning("配对答案文档 %s 识别失败，第三答案源为空：%s", companion.id, exc)
        return None

    companion.ocr_status = "done"
    companion.ocr_result_path = str(result.output_dir)
    companion.question_count = result.question_count
    companion.review_count = 0
    await db.commit()
    logger.info("配对答案文档 %s 已识别 %d 条答案", companion.id, result.question_count)
    return result.output_dir / EXTRACT_JSON_NAME


async def process_pdf_async(source_id: str, pdf_path: str, job_id: str) -> None:
    """API 大模型识别通道入口。

    签名与 ocr_service.process_pdf_async 保持一致，upload 与 retry 才能按
    Source.extract_channel 统一分发。通道参数从 Job.payload 与 Source 上读。
    """
    async with async_session_factory() as db:
        await mark_running(
            db, source_id, job_id, progress=5.0, channel=CHANNEL_API_EXTRACT
        )
        source = await db.get(Source, source_id)

        async def progress(value: float, stage: str | None = None) -> None:
            """刷新 Job 进度。

            run_extract 的进度回调发生在阶段之间（不在 asyncio.gather 内部），
            与本协程顺序执行，因此共用同一个 session 是安全的。
            """
            current = await db.get(Job, job_id)
            if current is None:
                return
            current.progress = float(value)
            await db.commit()
            logger.info("api_extract source=%s 进度 %.0f%% %s", source_id, value, stage or "")

        async def cancel_check() -> bool:
            return await is_cancelled(db, job_id)

        try:
            if await is_cancelled(db, job_id):
                await finish_cancelled(db, source_id, job_id)
                return

            current = await get_job(db, job_id)
            payload = parse_job_payload(current.payload if current else None)
            config = await get_vision_config(db)

            companion_json = await _ensure_companion_extract(
                db,
                source,
                config,
                progress=progress,
                cancel_check=cancel_check,
            )

            # 先清掉自述水印：题卡与插图是对页面矩形直接光栅化，水印会一起被栅格化进图。
            # 在识别之前、记账之外做（纯本地文件操作，不消耗 token）。
            pdf_for_ocr = await asyncio.to_thread(prepare_pdf, Path(pdf_path))

            # 记账范围只包住本卷识别：配对答案文档在 _ensure_companion_extract 里
            # 另跑一条管线，用量记在它自己的来源上，不混进本卷。
            with track_usage() as ledger:
                result: ExtractResult = await run_extract(
                    config,
                    pdf_for_ocr,
                    settings.ocr_output_dir,
                    subject=source.subject if source else None,
                    doc_kind_hint=payload.get("doc_kind") or None,
                    source_id=source_id,
                    companion_extract_json=companion_json,
                    progress=map_progress_band(progress, *MAIN_BAND),
                    cancel_check=cancel_check,
                    usage_ledger=ledger,
                )

            source = await db.get(Source, source_id)
            if source:
                source.ocr_status = STAGING_STATUS
                source.ocr_result_path = str(result.output_dir)
                source.extract_channel = CHANNEL_API_EXTRACT
                # 暂存期先把数量填上，列表页可直接显示「待确认 N 题」；
                # 用户在预览页剔除题目后，confirm 会用最终值覆盖。
                source.question_count = result.question_count
                source.review_count = result.review_count

            await finish_success(db, job_id)
            await db.commit()

            logger.info(
                "api_extract 暂存完成 source=%s：%d 题（待复核 %d），覆盖率 %.3f，闸门 %s，"
                "大模型 %d 次调用 / %d tokens",
                source_id,
                result.question_count,
                result.review_count,
                float(result.audit.get("coverage_ratio", 1.0)),
                "阻断" if result.blocked else "放行",
                ledger.calls,
                ledger.total_tokens,
            )

        except ExtractCancelled:
            await finish_cancelled(db, source_id, job_id)
        except VLMConfigError as exc:
            await finish_failed(db, source_id, job_id, f"视觉模型配置不可用：{exc}")
        except Exception as exc:  # noqa: BLE001 — 与 ocr_service 一致：记录并落 failed
            logger.exception("api_extract 失败 source=%s", source_id)
            await finish_failed(db, source_id, job_id, str(exc))
