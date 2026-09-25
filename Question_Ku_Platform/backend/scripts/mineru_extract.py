"""MinerU 识别通道的离线回归脚本（不进 pytest，改 prompt / 调适配层后手动跑）。

对 test_data/ 下的 PDF 真实调用 MinerU 官方 API + 视觉模型，跑完整条识别管线，
产出与 ``golden_extract.py`` **同一套**验收指标（题数 / 覆盖率 / 答案匹配 /
孤儿页 / 闸门）—— 两份脚本的结论可以直接摆在一起对照，这是回答
「MinerU 与 api_extract 哪个切得好」唯一靠谱的办法。

用法（在 ``backend/`` 目录下）::

    python -m scripts.mineru_extract --token sk-xxx
    python -m scripts.mineru_extract -f ../test_data/2026河东区一模物理试卷.pdf --token sk-xxx
    python -m scripts.mineru_extract --reuse        # 复用已下载的结果包，不再花额度
    python -m scripts.mineru_extract --no-check

Token 解析顺序：``--token`` → 环境变量 ``MINERU_API_TOKEN`` → 数据库设置
（与生产同一条路，可在设置页填好后直接跑）。

``--reuse`` 的意义：结果包留档在 ``<out-root>/<文档名>/mineru/`` 下，改 prompt
或适配层时可以反复重跑下游管线，不再消耗 MinerU 的每日页数额度。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

PROJECT_DIR = BACKEND_DIR.parent
TEST_DATA_DIR = PROJECT_DIR / "test_data"

# 先 import api_extract 包：它的 __init__ 会把 packages/ 注入 sys.path，
# 之后 service 才能 import physics_paper_splitter（顺序不能反）。
from app.config import settings  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.services.api_extract.service import run_extract  # noqa: E402
from app.services.api_extract.vlm_client import (  # noqa: E402
    VLMConfigError,
    get_vision_config,
)
from app.services.api_extract_adapter import (  # noqa: E402
    CHANNEL_MINERU,
    resolve_document_dir,
)
from app.services.mineru_adapter import (  # noqa: E402
    build_figure_candidates,
    build_lines,
    page_sizes_from_pdf,
)
from app.services.mineru_client import (  # noqa: E402
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL_VERSION,
    MineruConfigError,
    artifacts_from_zip,
    get_mineru_config,
    parse_pdf,
)
from app.utils.pdf_watermark import prepare_pdf  # noqa: E402
from scripts.golden_extract import (  # noqa: E402
    DocReport,
    SourceMarkers,
    build_report,
    scan_source_markers,
)

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

MINERU_SUBDIR = "mineru"


async def run_one(
    mineru_config: dict, vision_config: dict, pdf_path: Path, args
) -> DocReport:
    """单份文档：MinerU 解析（或复用）→ 翻译 → 识别管线 → 验收报告。

    mineru_config 是 MinerU 通道配置（Token + 解析参数），vision_config 是
    识别管线要用的视觉模型配置。
    """
    markers = scan_source_markers(pdf_path)
    out_root = Path(args.out_root) if args.out_root else settings.ocr_output_dir
    document_name = f"{pdf_path.stem}{args.name_suffix}"
    document_dir = resolve_document_dir(out_root, document_name)
    work_dir = document_dir / MINERU_SUBDIR

    def mineru_progress(ratio: float, stage: str | None = None) -> None:
        print(f"\r    MinerU {ratio * 100:5.1f}%  {(stage or ''):<14}", end="", flush=True)

    def pipeline_progress(value: float, stage: str | None = None) -> None:
        print(f"\r    管线   {value:5.1f}%  {(stage or ''):<14}", end="", flush=True)

    print(f"[跑] {pdf_path.name}（{markers.pages} 页）-> {document_dir}")
    # 与生产 mineru_service 同一步预处理：先清自述水印再交给 MinerU。
    # 不做这一步，回归脚本测的输入就和生产的不是同一份，--reuse 重放时结论对不上。
    pdf_for_run = await asyncio.to_thread(prepare_pdf, pdf_path)
    try:
        if args.reuse:
            zip_path = work_dir / f"{pdf_path.stem}.zip"
            if not zip_path.exists():
                raise FileNotFoundError(f"--reuse 但结果包不存在：{zip_path}")
            artifacts = await asyncio.get_event_loop().run_in_executor(
                None, artifacts_from_zip, zip_path, work_dir
            )
            print(f"\r    [reuse] {zip_path.name}")
        else:
            artifacts = await parse_pdf(
                mineru_config["token"],
                pdf_for_run,
                work_dir,
                model_version=mineru_config["model_version"],
                language=mineru_config["language"],
                enable_formula=mineru_config["enable_formula"],
                enable_table=mineru_config["enable_table"],
                progress=mineru_progress,
            )
    finally:
        print("\r" + " " * 52 + "\r", end="")

    if artifacts.content_list_path is None:
        raise RuntimeError(
            f"MinerU 结果包里没有 content_list.json，无法切题。成员：{artifacts.members[:10]}"
        )

    page_sizes = page_sizes_from_pdf(pdf_for_run)
    inventory = build_lines(artifacts.content_list_path, page_sizes=page_sizes)
    if not inventory.lines:
        raise RuntimeError("MinerU 没有解析出任何文字块，无法切题")
    # 插图也用它自己的，与 mineru_service 完全一致。原来这里只换行清单、插图仍走本地
    # 内嵌位图抽取，测的是"MinerU 老路径" —— 那条路拿不到矢量图，也拿不到表格/图表的
    # 渲染图（表格的 HTML 还只能靠模型转 Markdown，合并单元格必丢），回归结论与生产
    # 不是一回事。
    figures = build_figure_candidates(
        artifacts.content_list_path,
        page_sizes=page_sizes,
        images_root=artifacts.extract_dir,
    )
    figures_override = figures.candidates or None
    # 表格规则由 service 按题判断（候选自带 kind，归属仲裁后统计每题表格图数），
    # 这里不再全局定夺 —— 与 mineru_service 保持同一条路径。
    print(
        f"     行清单 {len(inventory.lines)} 行"
        f"（剔除噪声 {inventory.stats['noise_dropped']} 块、补题注 "
        f"{inventory.stats['caption_added']} 行）"
    )
    print(
        f"     插图候选 {len(figures.candidates)} 张，表格 "
        f"{figures.stats['tables_usable']}/{figures.stats['tables_total']} 张有渲染图"
        f"（表格规则由 service 按题判断）"
    )
    print(f"     MinerU 耗时 {artifacts.timings.get('合计', '-')}s")

    try:
        # 传清洗副本：题卡/插图是对页面矩形直接光栅化，传原文件会把水印一起栅格化进图。
        result = await run_extract(
            vision_config,
            pdf_for_run,
            out_root,
            document_name=document_name,
            subject=args.subject or None,
            doc_kind_hint=None if args.doc_kind == "auto" else args.doc_kind,
            channel=CHANNEL_MINERU,
            lines_override=inventory.lines,
            figures_override=figures_override,
            override_warnings=[*inventory.warnings, *figures.warnings],
            progress=pipeline_progress,
        )
    finally:
        print("\r" + " " * 52 + "\r", end="")

    return build_report(pdf_path, result, markers)


async def resolve_config(args, db) -> dict:
    """参数来源：数据库设置（与生产同一条路）→ --token / --model-version / --language 覆盖。

    读不到数据库设置（例如 Token 还没填）**不在这里抛错**：--reuse 全程不调 API，
    而离线重放恰恰最常在「Token 没配好」或「额度用尽」时用，不该被配置拦住。
    """
    config = {
        "token": "",
        "model_version": DEFAULT_MODEL_VERSION,
        "language": DEFAULT_LANGUAGE,
        "enable_formula": True,
        "enable_table": True,
    }
    try:
        config.update(await get_mineru_config(db))
    except MineruConfigError:
        pass

    cli_token = (args.token or os.environ.get("MINERU_API_TOKEN") or "").strip()
    if cli_token:
        config["token"] = cli_token
    if args.model_version:
        config["model_version"] = args.model_version
    if args.language:
        config["language"] = args.language
    return config


async def main_async(args) -> int:
    files: list[Path] = []
    for raw in args.files:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        files.append(candidate)
    if not files:
        files = sorted(TEST_DATA_DIR.glob("*.pdf"))
    files = [path for path in files if path.exists() and path.suffix.lower() == ".pdf"]
    if not files:
        print(f"[FAIL] 没有找到可跑的 PDF（默认目录 {TEST_DATA_DIR}）")
        return 2

    settings.ensure_dirs()
    async with async_session_factory() as db:
        try:
            vision_config = await get_vision_config(db)
        except VLMConfigError as exc:
            print(f"[FAIL] 视觉模型不可用：{exc}")
            print("       MinerU 通道只替换了行清单，判边界/结构化仍走视觉模型，必须配置。")
            return 2
        except SQLAlchemyError as exc:
            print(f"[FAIL] 读取设置失败：{type(exc).__name__}: {exc}")
            print("       数据库 schema 与模型不一致，请先在 backend/ 下跑：alembic upgrade head")
            return 2
        mineru_config = await resolve_config(args, db)

    if not args.reuse and not mineru_config["token"]:
        print(
            "[FAIL] MinerU Token 不可用：未配置 MinerU Token，请先在「系统设置」里填写"
            "（也可以用 --token 或环境变量 MINERU_API_TOKEN 临时传入）"
        )
        return 2

    print(f"视觉模型：{vision_config['model']} @ {vision_config['base_url']}")
    print(
        f"MinerU   ：{mineru_config['model_version']} / {mineru_config['language']}"
        f"（公式 {mineru_config['enable_formula']}，表格 {mineru_config['enable_table']}）"
        f"{'（--reuse，不调 API）' if args.reuse else ''}"
    )
    print(f"待跑文档：{len(files)} 份\n")

    reports: list[DocReport] = []
    for pdf_path in files:
        try:
            reports.append(await run_one(mineru_config, vision_config, pdf_path, args))
        except Exception as exc:  # noqa: BLE001 — 单份失败不阻断其余，最后一起汇总
            print(f"[ERROR] {pdf_path.name}: {type(exc).__name__}: {exc}")
            reports.append(
                DocReport(
                    name=pdf_path.name,
                    path=str(pdf_path),
                    markers=SourceMarkers(),
                    checks=[("识别完成", False, f"{type(exc).__name__}: {exc}")],
                )
            )
        print()

    print("=" * 96)
    print("MinerU 通道回归结果")
    print("=" * 96)
    failed = 0
    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        # --no-check 只改退出码、不改判定；不加注会让人误以为「跳过断言＝随便 PASS」。
        if args.no_check:
            status += "（--no-check，不计入退出码）"
        match = (
            f"{report.answer_match_ratio:.1%}"
            if report.answer_match_ratio is not None
            else "-"
        )
        print(f"\n[{status}] {report.name}（doc_kind={report.doc_kind}，"
              f"{report.markers.pages} 页）")
        print(f"       题数 {report.question_count} / 待复核 {report.review_count}"
              f" / 覆盖率 {report.coverage_ratio:.1%}（丢失 {report.lost_chars} 字）")
        print(f"       答案匹配 {match} / 孤儿页 {report.orphan_pages or '无'}"
              f" / 闸门 {'阻断' if report.blocked else '放行'}")
        print(f"       产物目录 {report.result_dir}")
        if report.reasons:
            for reason in report.reasons:
                print(f"       闸门：{reason}")
        for name, ok, note in report.checks:
            print(f"       [{'OK' if ok else 'FAIL'}] {name}：{note}")
        if report.labels and not report.passed:
            print(f"       切出编号：{report.labels}")
        if not report.passed:
            failed += 1

    if args.json:
        target = Path(args.json)
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "channel": "mineru",
                    # 两个都取**本次真正用到的**配置，不能取 CLI 原值：--model-version
                    # 没传时 args 里是 None，而实际用的是数据库设置里的后端。
                    "model_version": mineru_config["model_version"],
                    "vision_model": vision_config["model"],
                    "reports": [report.to_dict() for report in reports],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n结果已写入 {target}")

    if args.no_check:
        print(f"\n--no-check：跳过断言（{len(reports)} 份已跑完）。")
        return 0

    print(f"\n{len(reports) - failed}/{len(reports)} 份通过验收。")
    return 0 if failed == 0 else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MinerU 识别通道回归：真实调 MinerU API + 视觉模型跑完整条管线。",
    )
    parser.add_argument("files", nargs="*", help="待跑 PDF，可省略（默认 test_data/*.pdf）。")
    parser.add_argument(
        "-f", "--file", dest="file_opts", action="append", default=[],
        help="待跑 PDF，可重复传入（与位置参数等价）。",
    )
    parser.add_argument("--token", default=None, help="MinerU Token（也可用环境变量）。")
    parser.add_argument(
        "--model-version", default=None,
        help=f"MinerU 解析后端（vlm / pipeline）；默认取系统设置（当前默认 {DEFAULT_MODEL_VERSION}）。",
    )
    parser.add_argument(
        "--language", default=None,
        help=f"文档语言（ch / ch_server / en / japan…）；默认取系统设置（当前默认 {DEFAULT_LANGUAGE}）。",
    )
    parser.add_argument(
        "--doc-kind", choices=["auto", "paper", "handout"], default="auto",
        help="文档形态提示；auto 表示交给模型判定。",
    )
    parser.add_argument("--subject", default="物理", help="学科，决定公式严格度。")
    parser.add_argument(
        "--out-root", default=None,
        help="输出根目录，默认 settings.ocr_output_dir（必须留在 ocr_output 下，"
        "否则题卡图 URL 会 404）。",
    )
    parser.add_argument(
        "--name-suffix", default="__mineru", help="输出目录后缀，默认 __mineru。",
    )
    parser.add_argument(
        "--reuse", action="store_true",
        help="复用已下载的 MinerU 结果包，不再调用 API（省每日页数额度）。",
    )
    parser.add_argument("--json", default=None, help="把完整结果导出到该 JSON 文件。")
    parser.add_argument(
        "--no-check", action="store_true", help="只跑不断言，任何结果都返回 0。",
    )
    args = parser.parse_args(argv)
    args.files = list(args.files or []) + list(args.file_opts or [])
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
