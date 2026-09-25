"""MinerU 识别通道的 Job / Source 生命周期 —— 镜像 api_extract_service，止步于暂存区。

与 api_extract 的差别是**两处输入**：行清单和插图都不来自本地 PDF 解析，而是
MinerU 解析 → content_list 翻译得来。所以本模块的编排是：

    MinerU（申请链接 → 上传 → 轮询 → 下载解压）
      → content_list 翻译成 TextLine（mineru_adapter.build_lines）
      → content_list 的 image / chart / table 块翻译成插图候选
        （mineru_adapter.build_figure_candidates）
      → run_extract(lines_override=..., figures_override=...)  ← 其余阶段与 api_extract 同一条
      → Source 置 staging，等用户在预览页确认

插图为什么也换：本地那套 FigureExtractor 只认**内嵌位图**，而讲义/学案里的插图
多是 Word 画出来的**矢量线条图**（容器、电路、光路），本地一张都抽不到。实测某
讲义 75 题只抽到 36 张，MinerU 按版面切图给 79 张且包含那些矢量图。

为什么不把 MinerU 做成「本地 OCR 引擎」（像 rapidocr 那样挂进 packages/）：
本地引擎解决的是「把页面变成文字行」，坐标来自 PyMuPDF；MinerU 走网络、
拿到的是它自己版面分析后的块。两者的失败模式（文件超限/额度用尽/Token 过期
vs 引擎未安装）与进度形态（提交-轮询-下载 vs 即时返回）完全不同，
混进同一个模式串只会让错误提示说不清。产品上它就是一个独立通道。

**本通道仍然需要视觉模型配置**：MinerU 只替换了行清单，判题目边界、逐题
结构化、答案归一仍然是视觉模型在跑（见 run_extract）。所以「Token 填了但
AI 没开」会在提交后很快失败，两边的缺失必须报成两句不同的话。
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
    CHANNEL_MINERU,
    STAGING_STATUS,
    resolve_document_dir,
)
from app.services.mineru_adapter import (
    build_figure_candidates,
    build_lines,
    page_sizes_from_pdf,
)
from app.services.mineru_client import (
    MineruCancelled,
    MineruConfigError,
    MineruError,
    MineruTaskError,
    get_mineru_config,
    parse_pdf,
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

# 进度区间：MinerU 解析占前一段（提交/上传/轮询/下载），识别管线占后一段。
MINERU_BAND = (5.0, 30.0)
PIPELINE_BAND = (30.0, 95.0)

# MinerU 产物落在文档目录的这个子目录下：
#   mineru/<pdf 名>.zip     原始结果包（留档，便于离线复盘与重放，不重复花额度）
#   mineru/extract/         full.md / content_list.json / images/
# run_extract 的 _clean_generated_dirs 只清理 questions/ 与 figures/，不会碰它；
# delete_source 对整个文档目录 rmtree，生命周期天然对齐。
MINERU_SUBDIR = "mineru"


def _mineru_progress(emit):
    """把 MinerU 的 0~1 轮询进度映射到 MINERU_BAND。

    stage 带的是 MinerU 的原始状态（waiting-file / pending / running / converting），
    原样透给用户比只说「处理中」有用：卡在 waiting-file 说明文件还没传完，
    卡在 converting 说明在转格式，都指得到下一步该看哪里。
    """

    async def inner(ratio: float, stage: str | None = None) -> None:
        low, high = MINERU_BAND
        value = low + min(max(float(ratio), 0.0), 1.0) * (high - low)
        await emit(value, f"MinerU 解析（{stage}）" if stage else "MinerU 解析")

    return inner


async def process_pdf_async(source_id: str, pdf_path: str, job_id: str) -> None:
    """MinerU 识别通道入口。

    签名与 ocr_service / api_extract_service 的 process_pdf_async 保持一致，
    upload 与 retry 才能按 Source.extract_channel 统一分发。
    """
    async with async_session_factory() as db:
        await mark_running(
            db, source_id, job_id, progress=MINERU_BAND[0], channel=CHANNEL_MINERU
        )
        source = await db.get(Source, source_id)

        async def progress(value: float, stage: str | None = None) -> None:
            """刷新 Job 进度。

            MinerU 的轮询回调与 run_extract 的阶段回调都与本协程顺序执行，
            因此共用同一个 session 是安全的（与 api_extract_service 同样的前提）。
            """
            current = await db.get(Job, job_id)
            if current is None:
                return
            current.progress = float(value)
            await db.commit()
            logger.info("mineru source=%s 进度 %.0f%% %s", source_id, value, stage or "")

        async def cancel_check() -> bool:
            return await is_cancelled(db, job_id)

        try:
            if await is_cancelled(db, job_id):
                await finish_cancelled(db, source_id, job_id)
                return

            current = await get_job(db, job_id)
            payload = parse_job_payload(current.payload if current else None)
            # 两边配置都要读，且要在提交 MinerU 之前读 —— 缺视觉模型时让任务
            # 立刻失败，不要等 MinerU 白跑一遍再报错（还占了一次页数额度）。
            mineru_config = await get_mineru_config(db)
            config = await get_vision_config(db)

            pdf = Path(pdf_path)
            document_name = pdf.stem
            document_dir = resolve_document_dir(settings.ocr_output_dir, document_name)

            # 先清掉自述水印，再上传 —— 与本地 OCR / 大模型两条通道同一套预处理。
            # 本通道之前漏了这一步，于是传给 MinerU 的是**原始未清洗的 PDF**：
            # 题卡与插图是对页面矩形直接光栅化，水印会一起被栅格化进图；
            # MinerU 的 text block 也可能把水印文字收进正文。
            # 清洗是纯本地文件操作（不消耗 MinerU 额度），放线程池避免占事件循环。
            # prepare_pdf 的副本**保持同名**，故 document_name 不变、资产 URL 不失配。
            pdf_for_parse = await asyncio.to_thread(prepare_pdf, pdf)

            artifacts = await parse_pdf(
                mineru_config["token"],
                pdf_for_parse,
                document_dir / MINERU_SUBDIR,
                model_version=mineru_config["model_version"],
                language=mineru_config["language"],
                enable_formula=mineru_config["enable_formula"],
                enable_table=mineru_config["enable_table"],
                progress=_mineru_progress(progress),
                cancel_check=cancel_check,
            )
            if artifacts.content_list_path is None:
                raise MineruTaskError(
                    "MinerU 结果包里没有 content_list.json，无法切题。"
                    f"包内成员：{artifacts.members[:10]}"
                )

            # 页尺寸取自**上传的那份**（清洗副本），与 MinerU 解析的对象保持一致；
            # 清洗只替换 XObject 流，不改页面几何，故两者尺寸恒等。
            page_sizes = page_sizes_from_pdf(pdf_for_parse)
            inventory = build_lines(
                artifacts.content_list_path,
                page_sizes=page_sizes,
            )
            if not inventory.lines:
                raise MineruTaskError("MinerU 没有解析出任何文字块，无法切题")
            # 插图也用它自己的：本地那套只认**内嵌位图**，而讲义/学案里的插图多是
            # 矢量线条画（容器、电路、光路），本地一张都抽不到 —— 实测某讲义 75 题
            # 只抽到 36 张，MinerU 这边 79 张且包含那些矢量图。
            figures = build_figure_candidates(
                artifacts.content_list_path,
                page_sizes=page_sizes,
                images_root=artifacts.extract_dir,
            )
            figures_override = figures.candidates or None
            # 表格规则不再在这里全局定夺：插图候选自带块类型（kind），归属仲裁后
            # service 拿到「每题拿到渲染图的表格数」，结构化**按题**决定禁不禁
            # Markdown 重抄 —— 实测 9 张表里 1 张没图，会把其余 8 张有图的也拖回
            # Markdown（合并单元格必丢），全卷一票否决太粗。
            tables_as_figures = bool(
                figures.stats.get("tables_total")
                and figures.stats.get("tables_total") == figures.stats.get("tables_usable")
            )
            if figures_override is None:
                # 退回本地抽取也要说一声：否则"图上少了"会被当成识别质量问题。
                figures.warnings.append(
                    "MinerU 没有返回任何插图块，本次退回本地内嵌位图抽取。"
                )
            logger.info(
                "mineru source=%s 行清单 %d 行（剔除噪声 %d 块、补题注 %d 行），"
                "MinerU 阶段耗时 %.1fs",
                source_id,
                len(inventory.lines),
                inventory.stats["noise_dropped"],
                inventory.stats["caption_added"],
                float(artifacts.timings.get("合计", 0.0)),
            )

            # 记账只包住识别管线：MinerU 的调用不吃视觉模型的 token，
            # 混进同一个账本会让「这一卷花了多少 token」再也算不清。
            with track_usage() as ledger:
                # 这里必须传**清洗副本**而不是原文件：题卡图与插图是对页面矩形
                # 直接光栅化（QuestionCropper），传原文件的话水印会被一起栅格化
                # 进题卡 —— 只清解析、不清裁剪，等于白清一半。
                # 副本与源文件同名，故 document_name 与资产 URL 不受影响。
                result = await run_extract(
                    config,
                    pdf_for_parse,
                    settings.ocr_output_dir,
                    document_name=document_name,
                    subject=source.subject if source else None,
                    doc_kind_hint=payload.get("doc_kind") or None,
                    source_id=source_id,
                    channel=CHANNEL_MINERU,
                    lines_override=inventory.lines,
                    figures_override=figures_override,
                    override_warnings=[*inventory.warnings, *figures.warnings],
                    progress=map_progress_band(progress, *PIPELINE_BAND),
                    cancel_check=cancel_check,
                    usage_ledger=ledger,
                )

            source = await db.get(Source, source_id)
            if source:
                source.ocr_status = STAGING_STATUS
                source.ocr_result_path = str(result.output_dir)
                source.extract_channel = CHANNEL_MINERU
                # 暂存期先填数量，列表页可直接显示「待确认 N 题」；
                # 用户剔除题目后，confirm 会用最终值覆盖。
                source.question_count = result.question_count
                source.review_count = result.review_count

            await finish_success(db, job_id)
            await db.commit()

            logger.info(
                "mineru 暂存完成 source=%s：%d 题（待复核 %d），覆盖率 %.3f，闸门 %s，"
                "视觉模型 %d 次调用 / %d tokens",
                source_id,
                result.question_count,
                result.review_count,
                float(result.audit.get("coverage_ratio", 1.0)),
                "阻断" if result.blocked else "放行",
                ledger.calls,
                ledger.total_tokens,
            )

        except (MineruCancelled, ExtractCancelled):
            await finish_cancelled(db, source_id, job_id)
        except MineruConfigError as exc:
            # Token 没配/填错：用户要去改设置，不是重试能解决的。
            await finish_failed(db, source_id, job_id, str(exc))
        except MineruError as exc:
            await finish_failed(db, source_id, job_id, f"MinerU 解析失败：{exc}")
        except VLMConfigError as exc:
            await finish_failed(db, source_id, job_id, f"视觉模型配置不可用：{exc}")
        except Exception as exc:  # noqa: BLE001 — 与其它通道一致：记录并落 failed
            logger.exception("mineru 失败 source=%s", source_id)
            await finish_failed(db, source_id, job_id, str(exc))
