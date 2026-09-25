"""api_extract 通道的编排：行清单 -> 边界 -> 裁卡 -> 结构化 -> 答案 -> 审计 -> 暂存。

进度节点与 api_extract_service 里的 Job.progress 对齐：
      5  running
     10  行清单（含扫描页整页转写）
     30  LLM 边界判定
     60  裁题卡 + 抽插图
     75  逐题结构化
     88  三源答案归一
     95  覆盖率审计 + 写暂存
    100  staging（由 api_extract_service 落）

本模块不碰任何 DB 模型：配置由调用方读好传进来，进度与取消通过回调注入，
因此可以脱离 FastAPI 直接测试。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

import pymupdf as fitz

from physics_paper_splitter.audit import (
    CoverageReport,
    boundary_audit,
    coverage_audit,
    item_flags,
)
from physics_paper_splitter.cropper import QuestionCropper
from physics_paper_splitter.figures import (
    FigureCandidate,
    FigureExtractor,
    extract_candidate_figures,
)
from physics_paper_splitter.inspector import PDFInspector, split_vlm_pages
from physics_paper_splitter.lines import TextLine, lines_in_range
from physics_paper_splitter.quality import CompletenessValidator

from app.services.api_extract_adapter import (
    CHANNEL_API_EXTRACT,
    ExtractItemData,
    ExtractResult,
    now_iso,
    resolve_document_dir,
    write_extract_json,
)

from . import ExtractCancelled
from .usage import UsageLedger
from .answer_figures import (
    answer_needs_figures,
    assign_answer_figures,
    extract_answer_figures,
    plan_answer_figures,
    plan_stem_figure_refs,
    split_answer_blocks,
)
from .answers import (
    INLINE_ANSWER_RE,
    arbitrate_conflicts,
    load_companion_entries,
    parse_answer_key_deterministic,
    parse_answer_key_region,
    resolve_answers,
    trailing_number,
)
from .boundary import BoundaryResult, build_line_inventory, detect_boundaries
from .structure import structure_questions

logger = logging.getLogger(__name__)

# 这些 audit_flag 意味着内容可能不完整或边界可疑，必须人工过一眼；
# has_formula / figures:N 只是描述性标记，不触发复核。
REVIEW_FLAGS = {"no_answer", "cross_page", "tall_card", "no_segments"}


async def _tick(progress, value: float, stage: str | None = None) -> None:
    if progress is None:
        return
    result = progress(value, stage)
    if asyncio.iscoroutine(result):
        await result


async def _check_cancelled(cancel_check) -> None:
    if cancel_check is not None and await cancel_check():
        raise ExtractCancelled()


def _clean_generated_dirs(document_dir: Path) -> None:
    """questions/ 与 figures/ 完全由本通道管理，重跑前先清干净。

    与 SplitPipeline.process 同样的做法：否则上一次运行遗留的高题号图片
    会混进本次结果。
    """
    for name in ("questions", "figures"):
        target = document_dir / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def _no_text_pages(doc: fitz.Document, lines: list[TextLine]) -> set[int]:
    """有图却没有任何文字行的页（扫描插图页）；审计把它们计入孤儿页。"""
    with_lines = {line.page_index for line in lines}
    return {
        page_index
        for page_index in range(len(doc))
        if page_index not in with_lines and doc[page_index].get_images(full=True)
    }


def _raw_text(lines: list[TextLine], start_line: int, end_line: int) -> str:
    return "\n".join(line.text for line in lines_in_range(lines, start_line, end_line))


def _build_answer_report(
    items: list[ExtractItemData],
    global_warnings: list[str],
) -> dict:
    """答案归一的整体情况，预览页顶部与审计一起展示。"""
    matched = [item for item in items if item.answer]
    by_origin: dict[str, int] = {}
    for item in matched:
        if item.answer_origin:
            by_origin[item.answer_origin] = by_origin.get(item.answer_origin, 0) + 1
    total = len(items)
    return {
        "total": total,
        "matched": len(matched),
        "match_ratio": round(len(matched) / total, 4) if total else None,
        "by_origin": by_origin,
        "conflicts": [item.qid for item in items if item.answer_conflict],
        "unmatched": [item.qid for item in items if not item.answer],
        "warnings": list(global_warnings),
    }


def _assemble_items(
    boundary: BoundaryResult,
    structured: list,
    resolved: list,
    lines: list[TextLine],
    card_paths: dict[int, Path],
    figures_map: dict[int, list[str]],
    answer_figures_map: dict[int, list[str]],
    answer_figure_refs_map: dict[int, list[dict]],
    answer_blocks_map: dict[int, list[dict]] | None = None,
    boundary_flagged: set[int] | None = None,
    size_dropped_map: dict[int, int] | None = None,
    low_overlap_map: dict[int, int] | None = None,
) -> list[ExtractItemData]:
    """把四个下标对齐的列表拼成暂存条目。

    boundary.spans / boundary.records / structured / resolved 都以 qid 为序，
    这里用 dict 按 qid 取而不是 zip —— 结构化阶段单题失败不会改变列表长度，
    但用 qid 索引对将来的过滤/重排更稳。
    """
    structured_by_qid = {item.qid: item for item in structured}
    resolved_by_qid = {item.qid: item for item in resolved}
    items: list[ExtractItemData] = []

    for span, record in zip(boundary.spans, boundary.records):
        parsed = structured_by_qid.get(span.qid)
        answer = resolved_by_qid.get(span.qid)
        raw_text = _raw_text(lines, span.start_line, span.end_line)
        figures = figures_map.get(span.qid, [])

        stem_md = parsed.stem_md if parsed else ""
        # 结构化失败时回落到原始行文本：预览页至少能看到原文，而不是空白题卡。
        content = stem_md or raw_text

        has_answer = bool(answer and answer.answer)
        flags = item_flags(
            record,
            has_answer=has_answer,
            has_formula=bool(parsed and parsed.has_formula),
            figure_count=len(figures),
        )
        warnings: list[str] = list(record.warnings)
        if parsed:
            warnings.extend(parsed.warnings)
        needs_review = bool(
            (parsed.needs_review if parsed else True)
            or (answer.needs_review if answer else True)
            or (REVIEW_FLAGS & set(flags))
            or (boundary_flagged is not None and span.qid in boundary_flagged)
        )
        if answer and answer.note:
            warnings.append(answer.note)

        # 逐题提示"有图被当作装饰忽略了"：总告警只在摘要里，
        # 复核时人是按题看的，提示必须跟着题目走。
        dropped_figures = (size_dropped_map or {}).get(span.qid, 0)
        if dropped_figures:
            warnings.append(
                f"有 {dropped_figures} 张插图因尺寸偏小被当作装饰图忽略，"
                f"若本题看起来缺图，请对照原卷人工补上。"
            )

        # 图照收，但"只有一小角落在本题里"这件事要跟着题目提示：
        # 它可能是章节横幅（该删），也可能是跨页续页的图（该留），几何分不开，
        # 所以把判断交给人，只负责把注意力引过去。
        low_overlap = (low_overlap_map or {}).get(span.qid, 0)
        if low_overlap:
            warnings.append(
                f"有 {low_overlap} 张图只有一小部分落在本题区域内，"
                f"可能是章节横幅（如「随堂检测」）或跨页续页的插图，请核对后决定去留。"
            )

        # 边界判定给的类型/分值是弱证据，结构化结果更贴近题目本身；
        # 但结构化没给出时必须回落到边界值，不能把已有信息丢掉。
        question_type = (parsed.qtype if parsed else None) or span.qtype
        score = span.score
        if parsed and parsed.score is not None:
            score = parsed.score
        has_formula = bool(parsed and parsed.has_formula)
        # 模型不给数值置信度，只记二值：结构化失败 0.0 / 成功 1.0。
        confidence = 1.0 if parsed and not parsed.error else 0.0

        items.append(
            ExtractItemData(
                qid=span.qid,
                question_number=record.number,
                label=span.label,
                section=span.section,
                question_type=question_type,
                score=score,
                stem_md=stem_md,
                options=parsed.options if parsed else [],
                content=content,
                raw_text=raw_text,
                answer=answer.answer if answer else None,
                explanation=answer.explanation if answer else None,
                answer_origin=answer.origin if answer else None,
                answer_sources=[e.to_dict() for e in answer.evidences] if answer else [],
                answer_note=answer.note if answer else None,
                answer_conflict=bool(answer and answer.conflict),
                card_image=(
                    f"questions/{record.filename}" if card_paths.get(span.qid) else None
                ),
                figures=figures,
                answer_figures=answer_figures_map.get(span.qid, []),
                answer_figure_refs=answer_figure_refs_map.get(span.qid, []),
                answer_blocks=(answer_blocks_map or {}).get(span.qid, []),
                segments=[asdict(segment) for segment in record.segments],
                start_page=record.start_page,
                end_page=record.end_page,
                is_cross_page=record.is_cross_page,
                width_px=record.width_px,
                height_px=record.height_px,
                has_formula=has_formula,
                audit_flags=flags,
                warnings=warnings,
                error=parsed.error if parsed else "未执行结构化",
                needs_review=needs_review,
                llm_confidence=confidence,
            )
        )
    return items


def _lap(timings: dict[str, float], name: str, mark: list[float]) -> None:
    """分段计时：记下"距上一次打点"的耗时，并重置打点。

    用"打点"而不是 with 包住各阶段：阶段调用都是多行语句，逐个重新缩进
    容易改错，插一行打点则几乎无侵入。
    四个 VLM 阶段里三个串行，没有这个分布就只能靠 jobs 表总时长反推。
    """
    now = time.perf_counter()
    timings[name] = round(now - mark[0], 1)
    mark[0] = now


async def run_extract(
    config: dict,
    pdf_path: Path,
    output_root: Path,
    *,
    document_name: str | None = None,
    subject: str | None = None,
    doc_kind_hint: str | None = None,
    source_id: str | None = None,
    companion_extract_json: Path | str | None = None,
    channel: str = CHANNEL_API_EXTRACT,
    lines_override: list[TextLine] | None = None,
    figures_override: list[FigureCandidate] | None = None,
    override_warnings: Iterable[str] | None = None,
    progress=None,
    cancel_check=None,
    usage_ledger: UsageLedger | None = None,
) -> ExtractResult:
    """跑完整条识别管线并把结果写进暂存区，返回 ExtractResult。

    Args:
        config: get_vision_config 预先读出的视觉模型配置（并发阶段不能共享 session）。
        pdf_path: 上传的 PDF。
        output_root: 必须是 settings.ocr_output_dir —— 资产 URL 依赖路径里的
            'ocr_output' 片段，换目录会让题卡图全部 404。
        document_name: 输出子目录名，默认取 PDF 文件名主干。
        subject: 学科，决定公式严格度。
        doc_kind_hint: 人工指定的文档形态提示（paper / handout），可为空由模型判定。
        source_id: 写进暂存 JSON，便于前端与排查。
        companion_extract_json: 配对答案文档的 extract.json 路径（第三答案源）。
        channel: 写进 extract.json 的通道标识（预览页的通道标签读它）。
            复用本管线不等于就是这个通道，所以必须由调用方声明。
        lines_override: 由外部提供的行清单（MinerU 通道用 content_list 翻译而来）。
            传入时跳过本地文字层提取与扫描页整页转写，其余阶段完全不变 ——
            这正是 MinerU 通道能整条复用本管线的原因。**page_count 与 inspector
            仍然要跑**：detect_boundaries 需要 question_page_count 截断文末答案区。
        figures_override: 由外部提供的插图候选（MinerU 通道用 image / chart /
            table 块翻译而来）。
            传入时不做本地内嵌位图抽取，只按题目区域做归属仲裁并落盘。
            为什么需要这条：本地抽取只认**内嵌位图**，讲义/学案里的矢量线条图
            （容器、电路、光路）一张都拿不到；MinerU 按版面切图，矢量图也在里面。
            注意它与 lines_override 是**各自独立**的开关：只换行清单（MinerU 老路径）
            仍然走本地抽图，这也正是本次新开的这条路由。候选自带块类型（kind），
            结构化阶段据此**按题**决定表格规则（见 structure._tables_covered），
            不再是全卷一票否决的布尔。
        override_warnings: 外部来源自带的告警（MinerU 的噪声块统计、跳过的图片块等），
            合并进本次识别的 warnings，免得问题只留在上游日志里。
        progress: async/sync 可调用 (percent, stage)，用于更新 Job 进度。
        cancel_check: async 可调用，返回 True 表示用户已取消。
        usage_ledger: 大模型用量账本。传入时把本次用量写进 extract.json 的 usage；
            不传（离线脚本、测试）时留空字典，前端显示「未记录」。
    """
    pdf_path = Path(pdf_path)
    document_name = document_name or pdf_path.stem
    document_dir = resolve_document_dir(output_root, document_name)
    question_dir = document_dir / "questions"
    figures_dir = document_dir / "figures"

    warnings: list[str] = []
    timings: dict[str, float] = {}
    mark = [time.perf_counter()]
    await _tick(progress, 5.0, "running")

    # route 判定沿用 inspector 现有阈值：有效字符 < MIN_NATIVE_CHARS(100) 或替换字符 >= 3。
    inspection = PDFInspector().inspect(pdf_path)
    vlm_pages = {page.page_index for page in inspection.pages if page.route == "vlm"}
    # 触发原因必须分开报（理由见 split_vlm_pages 的 docstring）：合并成一句会把
    # 「有文字层、只是公式字形取不回」说成「没有可用文字层」。这句是**用户级**
    # 警告，不进诊断折叠，会直接显示给复核老师，说错了会让人以为卷子是扫描件。
    blank_pages, glyph_pages = split_vlm_pages(inspection)
    warnings.extend(inspection.warnings)

    if lines_override is None:
        tail = "改走视觉模型整页转写。"
    else:
        tail = "本次行清单由 MinerU 提供（它对扫描页做过识别），未再走视觉模型整页转写。"
    if blank_pages:
        warnings.append(f"第 {blank_pages} 页没有可用文字层，{tail}")
    if glyph_pages:
        warnings.append(
            f"第 {glyph_pages} 页有文字层，但含无法从字体取回的字符（多为公式），{tail}"
        )

    _clean_generated_dirs(document_dir)

    with fitz.open(pdf_path) as doc:
        page_count = len(doc)
        await _check_cancelled(cancel_check)

        await _tick(progress, 10.0, "行清单")
        if lines_override is not None:
            lines = list(lines_override)
            warnings.extend(override_warnings or [])
        else:
            lines, inventory_warnings = await build_line_inventory(
                config, doc, vlm_pages=vlm_pages, cancel_check=cancel_check
            )
            warnings.extend(inventory_warnings)
        if not lines:
            warnings.append("整份文档没有提取到任何文字行。")

        await _check_cancelled(cancel_check)
        _lap(timings, "行清单", mark)
        await _tick(progress, 30.0, "边界判定")
        boundary = await detect_boundaries(
            config,
            doc,
            lines,
            subject=subject,
            doc_kind_hint=doc_kind_hint,
            # 答案/解析区不产题：inspector 已按「参考答案」等标记算出题目页边界，
            # 没有独立答案区时它等于总页数，等价于不截断。
            question_page_count=inspection.question_page_count,
            cancel_check=cancel_check,
        )
        warnings.extend(boundary.warnings)

        # 确定性边界校验：零模型成本的形状检查（区间重叠 / 题号单调 / 首行
        # 题号 / 分题行覆盖），LLM 划界的系统性错误在这里被几何事实逮住。
        # 发现写进全局 warnings 与对应题卡的 warnings，并把该题标记为需复核。
        boundary_findings = boundary_audit(
            lines,
            boundary.records,
            boundary.spans,
            excluded_line_ids=boundary.excluded_line_ids,
            # 讲义形态只跑区间重叠：板块内题号重启、章节标题夹在题目之间、
            # 双栏排版，让首行题号与分题覆盖两条规则几乎全是误报。
            doc_kind=boundary.doc_kind,
        )
        boundary_flagged: set[int] = set()
        for finding in boundary_findings:
            warnings.append(f"确定性边界校验：{finding.detail}")
            boundary_flagged.add(finding.qid)
            if 0 < finding.qid <= len(boundary.records):
                boundary.records[finding.qid - 1].warnings.append(
                    f"确定性边界校验：{finding.detail}"
                )
        if boundary_findings:
            warnings.append(
                f"确定性边界校验共发现 {len(boundary_findings)} 处可疑边界，"
                f"对应题目已标记 needs_review。"
            )

        await _check_cancelled(cancel_check)
        _lap(timings, "边界判定", mark)
        await _tick(progress, 60.0, "裁卡与抽图")
        cropper = QuestionCropper()
        figure_extractor = FigureExtractor()
        completeness = CompletenessValidator()
        # 两条取图路径（本地内嵌位图 / MinerU 版面切图）都往这里写，
        # 汇总是同一段代码，免得两个分支各写一遍、日后只改一处。
        low_overlap_map: dict[int, int] = {}
        # qid -> 成功落盘的表格渲染图数（MinerU 候选里 kind=table 的那些）。
        # 结构化阶段按题决定表格规则时用（structure._tables_covered）。
        table_counts_map: dict[int, int] = {}

        def _crop_all() -> tuple[dict[int, Path], dict[int, list[str]], dict]:
            paths: dict[int, Path] = {}
            for record in boundary.records:
                if not record.segments:
                    continue
                try:
                    paths[record.number] = cropper.crop(doc, record, question_dir)
                except Exception as exc:  # noqa: BLE001 — 单题裁卡失败不应中断整批
                    warnings.append(f"第 {record.number} 题裁卡失败：{exc}")
            if figures_override is not None:
                # MinerU 通道：图已由它按版面切好（矢量图也在里面），
                # 这里只做归属仲裁与命名落盘，不去页面上找内嵌位图。
                outcome = extract_candidate_figures(
                    boundary.records, figures_override, figures_dir
                )
                extracted = outcome.figures
                low_overlap_map.update(outcome.low_overlap)
                table_counts_map.update(outcome.table_counts)
                total = sum(len(v) for v in extracted.values())
                warnings.append(
                    f"插图来自 MinerU 版面切图，共 {total} 张（未使用本地内嵌位图抽取）"
                )
                if outcome.unreadable:
                    warnings.append(
                        f"有 {outcome.unreadable} 张 MinerU 插图读取失败或为空白，已跳过。"
                    )
            else:
                extracted = figure_extractor.extract_all(doc, boundary.records, figures_dir)
                low_overlap_map.update(figure_extractor.last_low_overlap)
                if figure_extractor.last_shared_reassigned:
                    warnings.append(
                        f"有 {figure_extractor.last_shared_reassigned} 张插图与多道题区域重叠，"
                        f"已各归交集最大的一道题"
                    )
                if figure_extractor.last_recurring_dropped:
                    warnings.append(
                        f"已忽略 {figure_extractor.last_recurring_dropped} 类跨页复现的装饰图"
                        f"（页眉/水印/logo）"
                    )
                if figure_extractor.last_blank_dropped:
                    warnings.append(
                        f"已忽略 {figure_extractor.last_blank_dropped} 张空白装饰图（分隔线/纯色块）"
                    )
                # 尺寸丢弃**必须留痕**：阈值再怎么调，总会有真图落在它下面
                # （手机、旋钮这类窄高实拍图）。静默丢弃的表现是"这题少了一张图且毫无提示"。
                if figure_extractor.last_size_dropped:
                    total = sum(figure_extractor.last_size_dropped.values())
                    detail = "、".join(
                        f"第 {number} 题 {count} 张"
                        for number, count in sorted(
                            figure_extractor.last_size_dropped.items()
                        )
                    )
                    warnings.append(
                        f"有 {total} 张插图因尺寸偏小被当作装饰图忽略（{detail}）；"
                        f"若这些题看起来缺图，请打开原卷核对。"
                    )
            qa = completeness.validate(boundary.records, question_dir)
            return paths, extracted, qa

        # 跨在题号边界上的章节横幅（「随堂检测」「课堂总结」这类）会落进这里。
        # 只提示不丢弃：同样的低重合，和平卷第 26 题是一张跨页续页的真插图。
        # 放在两个分支之外汇总：位图抽取与 MinerU 候选共用同一套归属口径。
        if low_overlap_map:
            total = sum(low_overlap_map.values())
            detail = "、".join(
                f"第 {number} 题 {count} 张"
                for number, count in sorted(low_overlap_map.items())
            )
            warnings.append(
                f"有 {total} 张图只有一小部分落在题目区域内（{detail}），"
                f"可能是章节横幅或跨页续页的插图，请复核时留意。"
            )

        card_paths, figures_map, qa = await asyncio.get_event_loop().run_in_executor(
            None, _crop_all
        )

        await _check_cancelled(cancel_check)
        _lap(timings, "裁卡与抽图", mark)
        await _tick(progress, 75.0, "逐题结构化")
        structured = await structure_questions(
            config,
            lines,
            boundary,
            card_paths,
            figures_map,
            subject=subject,
            table_figures_by_qid=table_counts_map or None,
            cancel_check=cancel_check,
        )

        await _check_cancelled(cancel_check)
        _lap(timings, "逐题结构化", mark)
        await _tick(progress, 88.0, "答案归一")
        labels = [(span.qid, span.label, span.section) for span in boundary.spans]
        inline_texts = {
            span.qid: _raw_text(lines, span.start_line, span.end_line)
            for span in boundary.spans
        }
        answer_key_llm = await parse_answer_key_region(config, lines, boundary)
        answer_key_regex = parse_answer_key_deterministic(doc, lines, boundary, pdf_path)
        companion_entries = load_companion_entries(companion_extract_json)
        if companion_extract_json and not companion_entries:
            warnings.append(
                f"配对答案文档 {Path(str(companion_extract_json)).parent.name} 没有可用的答案条目，"
                f"第三答案源为空。"
            )
        resolved, answer_warnings = resolve_answers(
            labels,
            structured,
            inline_texts=inline_texts,
            answer_key_llm=answer_key_llm,
            answer_key_regex=answer_key_regex,
            companion_entries=companion_entries,
        )
        warnings.extend(answer_warnings)

        # 定向仲裁：只对 conflict=True 的题追加一次裁判调用，三态结论写进
        # note 供人工终审参考 —— answer/origin/conflict 一律不动，终审权在人工。
        conflicted = [answer for answer in resolved if answer.conflict]
        if conflicted:
            arbitration_results, arbitration_warnings = await arbitrate_conflicts(
                config, conflicted, labels, inline_texts, cancel_check=cancel_check
            )
            warnings.extend(arbitration_warnings)
            logger.info(
                "answer arbitration: %d/%d settled with a verdict",
                sum(1 for r in arbitration_results if r.verdict != "unclear"),
                len(conflicted),
            )

        await _check_cancelled(cancel_check)
        # 答案区插图：FigureExtractor 只看正文题目记录，答案本身是图的题在产物里
        # 连图都没有 —— 和平卷第 20 题卷面答案是一幅标了 R₁=15Ω/R₂=10Ω 的电路图、
        # 第 24 题 (2)(3) 只剩「如上图所示」「如上图2 所示」。这里按答案区的题号
        # 锚点把图补给它们，否则这几道题的答案永远只能是一句空话。
        answer_region_lines = [
            line for line in lines if line.line_id in boundary.answer_key_line_ids
        ]
        number_by_qid: dict[int, int] = {}
        for span in boundary.spans:
            number = trailing_number(span.label)
            if number is not None:
                number_by_qid[span.qid] = number
        answer_wanted = {
            number_by_qid[answer.qid]
            for answer in resolved
            if answer.qid in number_by_qid
            and answer_needs_figures(answer.answer, bool(answer.evidences))
        }

        # 题干图的 xref（题号 -> {xref}）与 xref -> 文件名。答案区解答里常把题干
        # 配图重印一遍当讲解背景（实测第 24 题把题干 3 张图全重印了），那是重复，
        # 题干已经裁过并挂在 figures 上，答案区不能再裁一份。
        #
        # FigureExtractor 的 key 是记录顺序号（= qid），而答案区抽图按**原文题号**
        # 归属，这里必须对齐一次。题号在文档内不唯一（讲义分板块各自从 1 编号）时
        # 一律不排除 —— 宁可不省，也不能把别人的图当成"重印件"删掉。
        number_counts = Counter(number_by_qid.values())
        stem_xrefs: dict[int, set[int]] = {}
        stem_figure_name: dict[int, dict[int, str]] = {}
        stem_figure_index: dict[int, dict[int, int]] = {}
        for qid, number in number_by_qid.items():
            if number_counts[number] != 1:
                continue
            pairs = figure_extractor.last_xref_figure_pairs.get(qid, [])
            if not pairs:
                continue
            stem_xrefs[number] = {xref for xref, _name in pairs}
            stem_figure_name[number] = {xref: name for xref, name in pairs}
            stem_figure_index[number] = {
                xref: index for index, (xref, _name) in enumerate(pairs, start=1)
            }

        def _extract_answer_figs() -> tuple[dict[int, list[str]], dict[int, set[int]]]:
            plans, reused = plan_answer_figures(
                doc, answer_region_lines, answer_wanted, stem_xrefs=stem_xrefs
            )
            return extract_answer_figures(doc, plans, figures_dir), reused

        (
            answer_figures_by_number,
            reused_stem_xrefs,
        ) = await asyncio.get_event_loop().run_in_executor(None, _extract_answer_figs)
        answer_figures_map = {
            qid: answer_figures_by_number[number]
            for qid, number in number_by_qid.items()
            if number in answer_figures_by_number
        }
        if answer_figures_map:
            total_answer_figs = sum(len(paths) for paths in answer_figures_map.values())
            warnings.append(
                f"答案区补充了 {total_answer_figs} 张答案插图（{len(answer_figures_map)} 道题"
                f"的答案是图，卷面只写「如上图所示」），已挂在 answer_figures 上供核对。"
            )
        if reused_stem_xrefs:
            total_reused = sum(len(xrefs) for xrefs in reused_stem_xrefs.values())
            warnings.append(
                f"答案区排除了 {total_reused} 张题干图重印件（{len(reused_stem_xrefs)} 道题"
                f"在解答里重印了题干配图，题干已裁过，不重复裁）。"
            )

        # 多小问答案把图挂到对应小问下（第 24 题 (2) 电路图、(3) 描点图象），
        # 笼统挂在题级要靠人自己对顺序。只有真的拆出小问结构才产出分块 ——
        # 单段答案前端走原有的题级渲染。
        answer_blocks_map: dict[int, list[dict]] = {}
        for answer in resolved:
            figures = answer_figures_map.get(answer.qid)
            if not figures or not answer.answer:
                continue
            blocks = split_answer_blocks(answer.answer)
            if not any(block["label"] for block in blocks):
                continue
            assign_answer_figures(blocks, figures)
            answer_blocks_map[answer.qid] = blocks

        # 排除重印件后一张答案图都不剩的题：它的答案就是题干那张图本身 ——
        # 标注指向题干图，而不是再裁一份。
        refs_by_number = plan_stem_figure_refs(
            reused_stem_xrefs,
            answer_figures_by_number,
            stem_figure_name,
            stem_figure_index,
        )
        answer_figure_refs_map = {
            qid: refs_by_number[number]
            for qid, number in number_by_qid.items()
            if number in refs_by_number
        }
        if answer_figure_refs_map:
            warnings.append(
                f"有 {len(answer_figure_refs_map)} 道题的答案就是题干图本身，"
                f"已标注 answer_figure_refs 指向题干图，未重复裁图。"
            )

        await _check_cancelled(cancel_check)
        _lap(timings, "答案归一", mark)
        await _tick(progress, 95.0, "审计")
        items = _assemble_items(
            boundary,
            structured,
            resolved,
            lines,
            card_paths,
            figures_map,
            answer_figures_map,
            answer_figure_refs_map,
            answer_blocks_map,
            boundary_flagged,
            figure_extractor.last_size_dropped,
            low_overlap_map,
        )
        answer_report = _build_answer_report(items, answer_warnings)
        # 没有答案源就不做答案匹配断言：answer_total 恒等于题数，纯题目卷
        # （本就不带答案）会被 100% 阻断、永远无法入库。缺失答案靠这条
        # warning 暴露，而不是靠拦住整份文档。
        has_answer_source = bool(
            companion_entries
            or boundary.answer_key_line_ids
            or any(INLINE_ANSWER_RE.search(text or "") for text in inline_texts.values())
        )
        if not has_answer_source:
            warnings.append(
                "未找到答案源（行内【答案】/文末答案区/配对答案文档）："
                f"跳过答案匹配率闸门，{len(items)} 道题的答案需人工核对。"
            )
        audit: CoverageReport = coverage_audit(
            lines,
            boundary.records,
            page_count,
            excluded_line_ids=boundary.excluded_line_ids,
            no_text_pages=_no_text_pages(doc, lines),
            answer_total=len(items),
            answer_matched=answer_report["matched"],
            answer_applicable=has_answer_source,
        )

    result = ExtractResult(
        output_dir=document_dir,
        doc_kind=boundary.doc_kind,
        items=items,
        audit=audit.to_dict(),
        qa=qa,
        answer_report=answer_report,
        non_question_regions=[region.to_dict() for region in boundary.regions],
        warnings=warnings,
        # LLM 划界区间落盘：确定性边界校验的输入，也是离线复盘唯一可靠的依据
        # （从裁图几何反推会让相邻区间共享边界行，span_overlap 满屏误报）。
        boundary_spans=[
            {
                "qid": span.qid,
                "label": span.label,
                "start_line": span.start_line,
                "end_line": span.end_line,
            }
            for span in boundary.spans
        ],
        source_id=source_id,
        document_name=document_name,
        # 写进 extract.json 的通道标识：预览页顶部的通道标签读的就是它。
        # 不给默认值会让 MinerU 的产物显示成「API 大模型」，用户看到的是错的通道名。
        channel=channel,
        created_at=now_iso(),
        usage=usage_ledger.to_dict() if usage_ledger else {},
        timings=timings,
    )
    _lap(timings, "审计", mark)
    write_extract_json(document_dir, result)
    logger.info(
        "api_extract done: %s: %s items, coverage=%.3f, blocked=%s, answers=%s/%s",
        document_name, len(items), audit.coverage_ratio, audit.blocked,
        answer_report["matched"], answer_report["total"],
    )
    logger.info(
        "api_extract timings(s): %s（合计 %.1fs）",
        ", ".join(f"{name}={value}" for name, value in timings.items()),
        sum(timings.values()),
    )
    return result
