"""诊断覆盖率缺口：dump 行清单与边界中间态，供离线反复试算。

扫描件没有文字层，行清单靠 VLM 整页转写得来，无法离线复现 —— 所以先把
(lines / spans / regions / records / audit) 落到一个 JSON 里，之后改规则
只需要离线重算 coverage_audit，不必再烧一次调用。

用法：python scripts/_diag_coverage.py "<pdf 绝对路径>" <输出 json>
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pymupdf as fitz  # noqa: E402

from app.database import async_session_factory  # noqa: E402
from app.services.api_extract import boundary as boundary_mod  # noqa: E402
from app.services.api_extract.boundary import (  # noqa: E402
    build_line_inventory,
    detect_boundaries,
)
from app.services.api_extract.vlm_client import get_vision_config  # noqa: E402
from physics_paper_splitter.audit import coverage_audit  # noqa: E402
from physics_paper_splitter.inspector import PDFInspector  # noqa: E402


def _no_text_pages(doc: fitz.Document, lines) -> set[int]:
    with_lines = {line.page_index for line in lines}
    return {
        page_index
        for page_index in range(len(doc))
        if page_index not in with_lines and doc[page_index].get_images(full=True)
    }


async def main() -> None:
    pdf_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    async with async_session_factory() as db:
        config = await get_vision_config(db)

    inspection = PDFInspector().inspect(pdf_path)
    vlm_pages = {page.page_index for page in inspection.pages if page.route == "vlm"}
    print(f"页数 {len(inspection.pages)} | vlm 页 {sorted(p + 1 for p in vlm_pages)}")
    print(f"题目页 {inspection.question_page_count} | 答案起始页 {inspection.answer_start_page}")

    with fitz.open(pdf_path) as doc:
        page_count = len(doc)
        lines, warnings = await build_line_inventory(config, doc, vlm_pages=vlm_pages)
        print(f"行清单 {len(lines)} 行")

        boundary = await detect_boundaries(
            config,
            doc,
            lines,
            doc_kind_hint="paper",
            question_page_count=inspection.question_page_count,
        )

        report = coverage_audit(
            lines,
            boundary.records,
            page_count,
            excluded_line_ids=boundary.excluded_line_ids,
            no_text_pages=_no_text_pages(doc, lines),
            answer_total=len(boundary.spans),
            answer_matched=len(boundary.spans),
            answer_applicable=False,
        )

        index = {line.line_id: line for line in lines}
        spans_by_page: dict[int, list] = {}
        for record in boundary.records:
            for segment in record.segments:
                spans_by_page.setdefault(segment.page_index, []).append(
                    (segment.y0, segment.y1)
                )

        rows = []
        for line in lines:
            covered = any(
                y0 - 0.5 <= line.y0 <= y1 + 0.5
                for y0, y1 in spans_by_page.get(line.page_index, [])
            )
            rows.append(
                {
                    "line_id": line.line_id,
                    "page": line.page_index + 1,
                    "y0": round(line.y0, 1),
                    "y1": round(line.y1, 1),
                    "text": line.text,
                    "excluded": line.line_id in boundary.excluded_line_ids,
                    "covered": covered,
                }
            )

        payload = {
            "pdf": str(pdf_path),
            "page_count": page_count,
            "question_page_count": inspection.question_page_count,
            "lines": rows,
            "spans": [
                {
                    "qid": s.qid,
                    "label": s.label,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                }
                for s in boundary.spans
            ],
            "regions": [
                {"start_line": r.start_line, "end_line": r.end_line, "kind": r.kind}
                for r in boundary.regions
            ],
            "segments": [
                {
                    "number": record.number,
                    "label": record.label,
                    "segments": [
                        {
                            "page": seg.page_index + 1,
                            "y0": round(seg.y0, 1),
                            "y1": round(seg.y1, 1),
                        }
                        for seg in record.segments
                    ],
                }
                for record in boundary.records
            ],
            "audit": report.to_dict() if hasattr(report, "to_dict") else report.__dict__,
            "warnings": warnings + boundary.warnings,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(
        f"覆盖率 {report.coverage_ratio:.1%} | 丢失 {report.lost_chars} 字 | "
        f"覆盖 {report.covered_lines}/{report.total_lines} 行 | 排除 {report.excluded_lines} 行"
    )
    print(f"已写入 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
