"""跨卷校准 boundary_audit 的误报率（零模型成本，只读不写）。

为什么需要它：和平卷只暴露 1 个已知缺陷，校验 1 命中 0 误报 —— 样本量为 1，
「没误报」根本不能当结论。本脚本把校验放到更多卷上跑，看它报多少、报的是
不是真问题。

怎么用：

    venv/Scripts/python.exe backend/scripts/_calibrate_boundary_audit.py
    venv/Scripts/python.exe backend/scripts/_calibrate_boundary_audit.py --top 30

方法上的三个限制，先说清楚，免得数字被误读：
1. **只吃落盘的 boundary_spans**。extract.json 从 2026-09-13 起把 LLM 给的
   start_line/end_line 落盘；早期产物没有这个字段，只能从裁图几何反推，
   而反推出来的相邻区间必然共享边界行 —— 实测反推法在和平卷报 20 处
   span_overlap，真跑只报 1 处，全是伪影。故本脚本遇到无 spans 的产物直接跳过。
2. **扫描件用不了**。河东卷 10 页几乎没有文字层，它的行来自 VLM 转写，
   坐标与裁图几何不同源，几何校验对它没有意义，故不纳入。
3. **判真伪仍然要靠人**。脚本只负责「报多少、报在哪」，报出来的每一条
   是不是真问题，得对着 PDF 看。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

import pymupdf as fitz  # noqa: E402
from physics_paper_splitter.audit import (  # noqa: E402
    TOLERANCE_PT,
    boundary_audit,
)
from physics_paper_splitter.lines import extract_line_inventory  # noqa: E402
from physics_paper_splitter.models import CropSegment, QuestionRecord  # noqa: E402

OCR = ROOT / "data/ocr_output"
TEST_DATA = ROOT / "test_data"

CASES = [
    ("和平卷（试卷 · 26 题）", "2022年天津市和平区中考物理一模试卷.pdf", "__v12"),
    ("暑期卷讲义（讲义 · 75 题）", "物-9暑-05-固体、液体压强选择-吴马倩.pdf", "__v12"),
]


@dataclass
class Span:
    """duck-typed 的行区间，字段与 api_extract.boundary.QuestionSpan 对齐。"""

    qid: int
    label: str | None
    start_line: int
    end_line: int


def _records_and_spans(doc: dict, lines):
    """records 来自裁图几何，行区间只认落盘的 boundary_spans。

    没有 boundary_spans 的产物返回 None —— 从几何反推会让相邻区间共享
    边界行，span_overlap 必然满屏误报，那种数字没有校准价值。
    """
    raw_spans = doc.get("boundary_spans") or []
    if not raw_spans:
        return None, None

    records: list[QuestionRecord] = []
    spans: list[Span] = []
    for index, item in enumerate(doc["items"], start=1):
        segments = [
            CropSegment(
                page_index=seg["page_index"],
                x0=seg["x0"],
                y0=seg["y0"],
                x1=seg["x1"],
                y1=seg["y1"],
            )
            for seg in (item.get("segments") or [])
        ]
        if not segments:
            continue
        records.append(
            QuestionRecord(
                number=item.get("question_number") or index,
                filename=item.get("card_image") or f"Q{index:03d}.webp",
                start_page=(segments[0].page_index + 1),
                end_page=(segments[-1].page_index + 1),
                is_cross_page=len(segments) > 1,
                segments=segments,
            )
        )
        row = raw_spans[index - 1] if index - 1 < len(raw_spans) else None
        spans.append(
            Span(
                qid=index,
                label=item.get("label"),
                start_line=int(row["start_line"]) if row else 0,
                end_line=int(row["end_line"]) if row else -1,
            )
        )
    return records, spans


def run_one(pdf: Path, extract_dir: Path, top: int) -> dict | None:
    doc = json.loads((extract_dir / "extract.json").read_text(encoding="utf-8"))
    pdf_doc = fitz.open(pdf)
    lines = extract_line_inventory(pdf_doc)
    pdf_doc.close()
    records, spans = _records_and_spans(doc, lines)
    if records is None:
        print(
            f"\n[跳过] {extract_dir.name}：产物没有落盘 boundary_spans"
            f"（跑于落盘功能之前），反推区间不可用于校准。"
        )
        return None

    findings = boundary_audit(lines, records, spans, doc_kind=doc.get("doc_kind"))
    by_rule: dict[str, int] = {}
    for finding in findings:
        by_rule[finding.kind] = by_rule.get(finding.kind, 0) + 1

    print(f"\n{'=' * 78}")
    print(f"{pdf.name}  （{extract_dir.name}）")
    print(f"{'=' * 78}")
    print(f"文字层行数 {len(lines)} | 题数 {len(records)} | 形态 {doc.get('doc_kind')}")
    if not findings:
        print("校验未报任何问题。")
    else:
        print(f"共 {len(findings)} 处：{by_rule}")
        for finding in findings[:top]:
            print(f"  [{finding.kind}] qid={finding.qid} {finding.detail[:96]}")
        if len(findings) > top:
            print(f"  … 另有 {len(findings) - top} 处未列出")
    return {
        "pdf": pdf.name,
        "doc_kind": doc.get("doc_kind"),
        "lines": len(lines),
        "questions": len(records),
        "findings": len(findings),
        "by_rule": by_rule,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=20, help="每份卷最多打印多少条详情")
    args = parser.parse_args()

    summary = []
    for title, pdf_name, suffix in CASES:
        pdf = TEST_DATA / pdf_name
        extract_dir = OCR / f"{Path(pdf_name).stem}{suffix}"
        if not pdf.exists() or not extract_dir.exists():
            print(f"[跳过] {title}：缺少 {pdf.name} 或 {extract_dir.name}")
            continue
        print(f"\n### {title}")
        row = run_one(pdf, extract_dir, args.top)
        if row is not None:
            summary.append(row)

    print(f"\n{'=' * 78}")
    print("汇总")
    print(f"{'=' * 78}")
    for row in summary:
        print(
            f"  {row['pdf'][:34]:34s} 行 {row['lines']:5d} | 题 {row['questions']:3d} "
            f"| 报 {row['findings']:3d} | {row['by_rule'] or ''}"
        )
    print("\n注：河东卷为纯扫描件，行坐标与裁图几何不同源，不纳入几何校验。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
