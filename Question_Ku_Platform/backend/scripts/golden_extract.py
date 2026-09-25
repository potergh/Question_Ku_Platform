"""api_extract 通道的金标回归脚本（不进 pytest，改 prompt / 换模型后手动跑）。

对 ``test_data/`` 下的 PDF 真实调用视觉模型，跑完整条识别管线，输出
「题数 / 覆盖率 / 答案匹配率 / 孤儿页」对照表，并按验收线判定通过与否。

用法（在 ``backend/`` 目录下）::

    venv\\Scripts\\python.exe scripts\\golden_extract.py
    venv\\Scripts\\python.exe scripts\\golden_extract.py -f test_data/xxx.pdf --doc-kind handout
    venv\\Scripts\\python.exe scripts\\golden_extract.py --json scripts/reports/golden_extract.json
    venv\\Scripts\\python.exe scripts\\golden_extract.py --no-check   # 只跑不断言

验收线（计划「测试与验收」原文）:
    1. 讲义题目全部被切出（含 ``【例N】`` 与 ``随堂检测`` 两套编号）；
    2. 覆盖率 >= 95%；
    3. 行内 ``【答案】`` 全中；
    4. 无孤儿页。

任一条不满足则退出码非 0，便于接入 CI 或 pre-prompt-change 手检清单。

「全部被切出」的基准不从外部文件读，而是**直接从 PDF 文字层数标记**：
每一个 ``【例N】`` 就是一道例题，每一个 ``【答案】``（实测与 ``【难度】`` 一一配对）
就是一道题。这两条基准对讲义自洽，试卷无标记时该项自动跳过。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
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

import pymupdf as fitz  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

# 覆盖率闸门，与 physics_paper_splitter.audit.COVERAGE_FLOOR 保持一致。
COVERAGE_FLOOR = 0.95

# 原文标记：与 audit 无关，纯粹用于推「应该切出多少题」。
EXAMPLE_MARKER_RE = re.compile(r"【例\s*\d+】")
INLINE_ANSWER_MARKER = "【答案】"
SUIZANG_MARKER = "随堂检测"
# 切出结果里的编号：LLM 可能给「【例1】」也可能给「例1」。
EXAMPLE_LABEL_RE = re.compile(r"例\s*\d+")
SUIZANG_LABEL_RE = re.compile(r"随堂")
# 非例题的独立编号题（随堂检测 / 变式练等）。LLM 可能回「随堂检测-1」，
# 也可能只回纯序号「1、」「2.」——实测后者更常见（25 页讲义里随堂题全被
# 标成「1、」…「19、」），只认「随堂」会把已切出的题误判为未切出。
NUMBERED_LABEL_RE = re.compile(r"^\s*\d{1,3}\s*[、．.）)]")


@dataclass
class SourceMarkers:
    """从 PDF 文字层数出来的基准数字。"""

    pages: int = 0
    examples: int = 0  # 【例N】出现次数
    inline_answers: int = 0  # 【答案】出现次数，实测与题数 1:1
    suizang_blocks: int = 0  # 「随堂检测」出现次数（含目录页的提及）

    def to_dict(self) -> dict:
        return {
            "pages": self.pages,
            "examples": self.examples,
            "inline_answers": self.inline_answers,
            "suizang_blocks": self.suizang_blocks,
        }


@dataclass
class DocReport:
    """单份文档的回归结果。"""

    name: str
    path: str
    markers: SourceMarkers
    doc_kind: str = ""
    question_count: int = 0
    review_count: int = 0
    excluded_count: int = 0
    coverage_ratio: float = 0.0
    lost_chars: int = 0
    answer_match_ratio: float | None = None
    answer_matched: int = 0
    orphan_pages: list[int] = field(default_factory=list)
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    example_cut: int = 0
    suizang_cut: int = 0
    inline_answer_total: int = 0
    inline_answer_matched: int = 0
    labels: list[str] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    result_dir: str = ""

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "markers": self.markers.to_dict(),
            "doc_kind": self.doc_kind,
            "question_count": self.question_count,
            "review_count": self.review_count,
            "excluded_count": self.excluded_count,
            "coverage_ratio": self.coverage_ratio,
            "lost_chars": self.lost_chars,
            "answer_match_ratio": self.answer_match_ratio,
            "answer_matched": self.answer_matched,
            "orphan_pages": self.orphan_pages,
            "blocked": self.blocked,
            "reasons": self.reasons,
            "example_cut": self.example_cut,
            "suizang_cut": self.suizang_cut,
            "inline_answer_total": self.inline_answer_total,
            "inline_answer_matched": self.inline_answer_matched,
            "labels": self.labels,
            "checks": [{"name": n, "ok": ok, "note": note} for n, ok, note in self.checks],
            "passed": self.passed,
            "result_dir": self.result_dir,
        }


def scan_source_markers(pdf_path: Path) -> SourceMarkers:
    """数 PDF 文字层里的编号标记，作为「应该切出多少题」的基准。"""
    with fitz.open(pdf_path) as doc:
        pages = len(doc)
        text = "".join(page.get_text() for page in doc)
    return SourceMarkers(
        pages=pages,
        examples=len(EXAMPLE_MARKER_RE.findall(text)),
        inline_answers=text.count(INLINE_ANSWER_MARKER),
        suizang_blocks=text.count(SUIZANG_MARKER),
    )


def build_report(pdf_path: Path, result, markers: SourceMarkers) -> DocReport:
    """把 ExtractResult 折成对照表的一行 + 验收结论。"""
    audit: dict = result.audit or {}
    items = result.items
    kept = [item for item in items if not item.excluded]
    labels = [item.label or "" for item in kept]

    example_cut = sum(1 for label in labels if EXAMPLE_LABEL_RE.search(label))
    # 两种编号形式都认：显式带「随堂」的，或不带前缀的纯序号题。
    suizang_cut = sum(
        1
        for label in labels
        if SUIZANG_LABEL_RE.search(label)
        or (NUMBERED_LABEL_RE.match(label) and not EXAMPLE_LABEL_RE.search(label))
    )

    # 「行内【答案】全中」：题卡原始行文本里出现【答案】，答案字段就必须填上。
    inline = [item for item in kept if INLINE_ANSWER_MARKER in (item.raw_text or "")]
    inline_matched = [item for item in inline if item.answer]

    coverage = float(audit.get("coverage_ratio", 0.0))
    orphan = list(audit.get("orphan_pages") or [])
    report = DocReport(
        name=pdf_path.name,
        path=str(pdf_path),
        markers=markers,
        doc_kind=result.doc_kind,
        question_count=result.question_count,
        review_count=result.review_count,
        excluded_count=len(items) - len(kept),
        coverage_ratio=coverage,
        lost_chars=int(audit.get("lost_chars", 0)),
        answer_match_ratio=audit.get("answer_match_ratio"),
        answer_matched=int(audit.get("answer_matched", 0)),
        orphan_pages=orphan,
        blocked=bool(audit.get("blocked")),
        reasons=list(audit.get("reasons") or []),
        example_cut=example_cut,
        suizang_cut=suizang_cut,
        inline_answer_total=len(inline),
        inline_answer_matched=len(inline_matched),
        labels=labels,
        result_dir=str(result.output_dir),
    )

    checks: list[tuple[str, bool, str]] = []

    # 0. 切出题数必须 > 0。零切出时 total_lines==0 会让覆盖率恒为 100%，
    #    其余各项又都走「无标记，跳过」，只有这条能拦住静默失败。
    checks.append(
        (
            "切出题数>0",
            result.question_count > 0,
            f"{result.question_count} 题",
        )
    )

    # 0b. 审计闸门：blocked 必须判失败，此前只作为原因打印、不参与判定，
    #     导致「0 题 + 阻断」的扫描件照样 PASS。
    checks.append(
        (
            "审计闸门放行",
            not report.blocked,
            "；".join(report.reasons) if report.blocked else "放行",
        )
    )

    # 1. 覆盖率 >= 95%
    checks.append(
        (
            "覆盖率≥95%",
            coverage >= COVERAGE_FLOOR,
            f"{coverage:.1%}（丢失 {report.lost_chars} 字）",
        )
    )

    # 2. 无孤儿页
    checks.append(("无孤儿页", not orphan, f"孤儿页 {orphan or '无'}"))

    # 3. 行内【答案】全中
    if inline:
        checks.append(
            (
                "行内【答案】全中",
                len(inline_matched) == len(inline),
                f"{len(inline_matched)}/{len(inline)}",
            )
        )
    else:
        checks.append(("行内【答案】全中", True, "无行内答案标记，跳过"))

    # 4. 编号体系是否全部切出（只在原文有对应标记时才判定）
    if markers.examples:
        checks.append(
            (
                "【例N】全切出",
                example_cut == markers.examples,
                f"{example_cut}/{markers.examples}",
            )
        )
    else:
        checks.append(("【例N】全切出", True, "原文无【例N】标记，跳过"))

    if markers.inline_answers:
        checks.append(
            (
                "题数对齐【答案】数",
                result.question_count == markers.inline_answers,
                f"{result.question_count}/{markers.inline_answers}",
            )
        )

    if markers.examples and markers.suizang_blocks:
        checks.append(
            (
                "【例N】+随堂检测两套编号",
                example_cut > 0 and suizang_cut > 0,
                f"例 {example_cut} 题 / 随堂 {suizang_cut} 题",
            )
        )

    report.checks = checks
    return report


def _display_width(text: str) -> int:
    """按终端显示宽度算长度（CJK 占 2 列），否则中文表格会错位。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    gap = max(width - _display_width(text), 0)
    return " " * gap + text if right else text + " " * gap


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [_display_width(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], _display_width(cell))
    line = "  ".join(_pad(h, w) for h, w in zip(headers, widths))
    print(line)
    print("-" * _display_width(line))
    for row in rows:
        print("  ".join(_pad(c, w) for c, w in zip(row, widths)))


def _cell(report: DocReport) -> list[str]:
    match = (
        f"{report.answer_match_ratio:.1%}" if report.answer_match_ratio is not None else "-"
    )
    examples = (
        f"{report.example_cut}/{report.markers.examples}"
        if report.markers.examples
        else "-"
    )
    return [
        report.name,
        report.doc_kind,
        str(report.markers.pages),
        str(report.question_count),
        examples,
        f"{report.coverage_ratio:.1%}",
        match,
        ",".join(str(p) for p in report.orphan_pages) or "无",
        "阻断" if report.blocked else "放行",
    ]


async def run_one(config: dict, pdf_path: Path, args) -> DocReport:
    markers = scan_source_markers(pdf_path)
    out_root = Path(args.out_root) if args.out_root else settings.ocr_output_dir
    document_name = f"{pdf_path.stem}{args.name_suffix}"

    def progress(value: float, stage: str | None = None) -> None:
        # 单行刷新，避免 25 页讲义刷出上百行。
        print(
            f"\r    {value:5.1f}%  {(stage or ''):<12}",
            end="",
            flush=True,
        )

    print(f"[跑] {pdf_path.name}（{markers.pages} 页）-> {out_root / document_name}")
    try:
        result = await run_extract(
            config,
            pdf_path,
            out_root,
            document_name=document_name,
            subject=args.subject or None,
            doc_kind_hint=None if args.doc_kind == "auto" else args.doc_kind,
            progress=progress,
        )
    finally:
        print("\r" + " " * 48 + "\r", end="")

    return build_report(pdf_path, result, markers)


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
            config = await get_vision_config(db)
        except VLMConfigError as exc:
            print(f"[FAIL] 视觉模型不可用：{exc}")
            print("       请先在设置页配置 AI（端点 / API Key / 视觉模型），再跑本脚本。")
            return 2
        except SQLAlchemyError as exc:
            # 真实库 schema 落后于模型（缺列/缺表）时，不要甩栈，直接指路。
            print(f"[FAIL] 读取设置失败：{type(exc).__name__}: {exc}")
            print("       数据库 schema 与模型不一致，请先在 backend/ 下跑：alembic upgrade head")
            return 2

    print(f"视觉模型：{config['model']} @ {config['base_url']}")
    print(f"待跑文档：{len(files)} 份\n")

    reports: list[DocReport] = []
    for pdf_path in files:
        try:
            reports.append(await run_one(config, pdf_path, args))
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

    headers = [
        "文档",
        "形态",
        "页数",
        "切出题数",
        "例N切出",
        "覆盖率",
        "答案匹配",
        "孤儿页",
        "闸门",
    ]
    print("=" * 100)
    print("金标回归对照表")
    print("=" * 100)
    _print_table(headers, [_cell(report) for report in reports])

    print("\n" + "=" * 100)
    print("验收结论")
    print("=" * 100)
    failed = 0
    for report in reports:
        status = "PASS" if report.passed else "FAIL"
        # --no-check 只改退出码、不改判定；不加注会让人误以为「跳过断言＝随便 PASS」。
        if args.no_check:
            status += "（--no-check，不计入退出码）"
        print(f"\n[{status}] {report.name}  （doc_kind={report.doc_kind}）")
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
                    "model": config["model"],
                    "base_url": config["base_url"],
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
        description="api_extract 金标回归：对 test_data/ 的 PDF 真实跑一遍识别管线。",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="待跑 PDF，可省略（默认 test_data/*.pdf）。",
    )
    parser.add_argument(
        "-f",
        "--file",
        dest="file_opts",
        action="append",
        default=[],
        help="待跑 PDF，可重复传入（与位置参数等价）。",
    )
    parser.add_argument(
        "--doc-kind",
        choices=["auto", "paper", "handout"],
        default="auto",
        help="文档形态提示；auto 表示交给模型判定。",
    )
    parser.add_argument(
        "--subject",
        default="物理",
        help="学科，决定公式严格度（默认 物理）。",
    )
    parser.add_argument(
        "--out-root",
        default=None,
        help="输出根目录，默认 settings.ocr_output_dir（必须留在 ocr_output 下，"
        "否则题卡图 URL 会 404）。",
    )
    parser.add_argument(
        "--name-suffix",
        default="__golden",
        help="输出目录后缀，避免覆盖生产目录（默认 __golden）。",
    )
    parser.add_argument("--json", default=None, help="把完整结果导出到该 JSON 文件。")
    parser.add_argument(
        "--no-check",
        action="store_true",
        help="只跑不断言，任何结果都返回 0。",
    )
    args = parser.parse_args(argv)
    # 位置参数与 -f 合并，位置参数优先（keep order: 位置在前）。
    args.files = list(args.files or []) + list(args.file_opts or [])
    return args


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
