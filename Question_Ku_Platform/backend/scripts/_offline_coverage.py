"""离线试算：用 dump 出来的行清单重算 segments 与覆盖率，不烧任何调用。

dump 由 scripts/_diag_coverage.py 产出（扫描件的行清单靠 VLM 转写，无法离线复现）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pymupdf as fitz  # noqa: E402

from app.services.api_extract import boundary as boundary_mod  # noqa: E402
from physics_paper_splitter.audit import coverage_audit  # noqa: E402
from physics_paper_splitter.lines import TextLine  # noqa: E402

DUMP = Path(sys.argv[1])
PDF = sys.argv[2]


def main() -> None:
    d = json.loads(DUMP.read_text(encoding="utf-8"))
    lines = [
        TextLine(
            line_id=row["line_id"],
            page_index=row["page"] - 1,
            y0=row["y0"],
            y1=row["y1"],
            x0=40.0,
            x1=520.0,
            text=row["text"],
        )
        for row in d["lines"]
    ]
    line_index = {line.line_id: line for line in lines}
    lines_by_page: dict[int, list] = {}
    for line in lines:
        lines_by_page.setdefault(line.page_index, []).append(line)

    questions = [
        {
            "label": span["label"],
            "section": None,
            "qtype": None,
            "score": None,
            "start_line": span["start_line"],
            "end_line": span["end_line"],
        }
        for span in d["spans"]
    ]
    regions = list(d["regions"])
    excluded = {row["line_id"] for row in d["lines"] if row["excluded"]}

    with fitz.open(PDF) as doc:
        records = boundary_mod._build_records(
            doc,
            line_index,
            lines_by_page,
            questions,
            regions,
            question_page_count=d["question_page_count"],
        )
        audit = coverage_audit(
            lines,
            records,
            d["page_count"],
            excluded_line_ids=excluded,
            answer_total=len(questions),
            answer_matched=len(questions),
            answer_applicable=False,
        )

    empty = [record.number for record in records if not record.segments]
    print(f"题数 {len(records)} | 无片段题号 {empty}")
    print(f"覆盖率 {audit.coverage_ratio:.1%} | 丢失 {audit.lost_chars} 字 | "
          f"覆盖 {audit.covered_lines}/{audit.total_lines} 行")

    # 逐页 content_bottom 与每页实际末行，看看裁掉了多少
    with fitz.open(PDF) as doc:
        from physics_paper_splitter.splitter import QuestionSplitter

        splitter = QuestionSplitter()
        print("\n页 | content_bottom | 该页最后一行 y1 | 页高")
        for page_index in range(d["page_count"]):
            page_lines = lines_by_page.get(page_index, [])
            last = max((line.y1 for line in page_lines), default=0.0)
            print(
                f"  {page_index + 1:>2} | {splitter._content_bottom(doc[page_index]):>6.1f} "
                f"| {last:>6.1f} | {doc[page_index].rect.height:.0f}"
            )


if __name__ == "__main__":
    main()
