"""离线核对「答案区重印题干图」的排除结果（零模型成本）。

方案 C 的核心动作：答案区解答里重印的题干配图不重复裁，只标注指向题干图。
这个脚本用**已有产物**重建题目记录与题干图 xref，再跑一遍答案区抽图排定，
把「排除了哪几张、留下哪几张」打印出来 —— 不需要重跑管线。

用法：
    python -m scripts._verify_answer_figure_reuse <extract.json> <pdf> <question_page_count>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pymupdf as fitz  # noqa: E402

from app.services.api_extract.answer_figures import (  # noqa: E402
    answer_needs_figures,
    plan_answer_figures,
)
from physics_paper_splitter.figures import FigureExtractor, recurring_xrefs  # noqa: E402
from physics_paper_splitter.lines import extract_line_inventory  # noqa: E402
from physics_paper_splitter.models import CropSegment, QuestionRecord  # noqa: E402


def rebuild_records(items: list[dict]) -> list[QuestionRecord]:
    """从产物 items 重建题目记录：离线核对的唯一输入。"""
    records: list[QuestionRecord] = []
    for item in items:
        segments = [
            CropSegment(
                page_index=int(seg["page_index"]),
                x0=float(seg["x0"]),
                y0=float(seg["y0"]),
                x1=float(seg["x1"]),
                y1=float(seg["y1"]),
            )
            for seg in (item.get("segments") or [])
        ]
        records.append(
            QuestionRecord(
                number=int(item["qid"]),
                filename=f"Q{int(item['qid']):03d}.webp",
                start_page=int(item.get("start_page") or 0),
                end_page=int(item.get("end_page") or 0),
                is_cross_page=bool(item.get("is_cross_page")),
                segments=segments,
                label=item.get("label") or "",
            )
        )
    return records


def trailing_number(label: str) -> int | None:
    digits = ""
    for char in label.strip():
        if char.isdigit():
            digits += char
        elif digits:
            break
    return int(digits) if digits else None


def main() -> None:
    extract_path = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2])
    qpc = int(sys.argv[3])

    data = json.loads(extract_path.read_text(encoding="utf-8"))
    items = data["items"]
    doc = fitz.open(pdf_path)

    records = rebuild_records(items)
    extractor = FigureExtractor()
    # 只为拿 xref：不落盘，避免在产物目录里多出一份 figures/
    detailed = extractor.plan_ownership_with_xrefs(
        doc, records, recurring=recurring_xrefs(doc)
    )

    stem_name = {
        number: {xref: f"figures/Q{number:03d}_{i:02d}.webp" for i, (_p, _r, xref) in enumerate(entries, 1)}
        for number, entries in detailed.items()
    }
    stem_index = {
        number: {xref: i for i, (_p, _r, xref) in enumerate(entries, 1)}
        for number, entries in detailed.items()
    }

    number_by_qid = {}
    for item in items:
        number = trailing_number(item.get("label") or "")
        if number is not None:
            number_by_qid[int(item["qid"])] = number
    number_counts = Counter(number_by_qid.values())

    stem_xrefs: dict[int, set[int]] = {}
    for qid, number in number_by_qid.items():
        if number_counts[number] != 1:
            continue
        pairs = detailed.get(qid, [])
        if pairs:
            stem_xrefs[number] = {xref for _p, _r, xref in pairs}

    wanted = {
        number_by_qid[int(item["qid"])]
        for item in items
        if int(item["qid"]) in number_by_qid
        and answer_needs_figures(item.get("answer"), bool(item.get("answer_sources")))
    }

    answer_lines = extract_line_inventory(doc, range(qpc, doc.page_count))
    plans, reused = plan_answer_figures(
        doc, answer_lines, wanted, stem_xrefs=stem_xrefs
    )

    print(f"需要配图的题号：{sorted(wanted)}\n")
    for item in items:
        number = number_by_qid.get(int(item["qid"]))
        if number not in wanted:
            continue
        existing = item.get("answer_figures") or []
        kept = plans.get(number, [])
        dropped = reused.get(number, set())
        print(f"── 第 {number} 题 ──")
        print(f"  题干图: {[(stem_index[number].get(x), stem_name[number].get(x)) for x in sorted(stem_xrefs.get(number, []))]}")
        print(f"  排除重印件: {[(stem_index[number].get(x), stem_name[number].get(x)) for x in sorted(dropped)]}")
        print(f"  保留答案图: {len(kept)} 张  ← 产物现有 {len(existing)} 张")
        for page_index, rect in kept:
            print(f"      p{page_index + 1} y={rect.y0:.0f}-{rect.y1:.0f} w={rect.width:.0f}")
        print()

    doc.close()


if __name__ == "__main__":
    main()
