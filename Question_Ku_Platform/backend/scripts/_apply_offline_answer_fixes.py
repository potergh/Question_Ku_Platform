"""离线写回：把答案归一与答案区取图的新口径落进已有产物（零模型调用）。

背景：三项口径改动（答案区优先取图 / 逐字抄写+详略守卫 / answer_blocks 小问
分块）落地后，旧产物 extract.json 仍是旧值。这里用确定性重放把三项改动写回：

1. 重放 resolve_answers（regex 路现算、其余证据沿用产物）→ 更新
   answer / answer_origin / answer_conflict / answer_note / answer_sources；
2. 重放 plan_answer_figures（near/far 新口径）→ 重裁答案图、更新
   answer_figures，清掉不再被引用的 answer_Q*.webp；
3. split_answer_blocks + assign_answer_figures → 写 answer_blocks。

写回前先把 extract.json 复制为 extract.prev.json 留档。

用法：
    ../venv/Scripts/python.exe scripts/_apply_offline_answer_fixes.py <extract.json> <pdf> <question_page_count>
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "packages"))

import pymupdf as fitz  # noqa: E402

from app.services.api_extract.answer_figures import (  # noqa: E402
    answer_needs_figures,
    assign_answer_figures,
    extract_answer_figures,
    plan_answer_figures,
    plan_stem_figure_refs,
    split_answer_blocks,
)
from app.services.api_extract.answers import resolve_answers  # noqa: E402
from physics_paper_splitter.answers import parse_answers  # noqa: E402
from physics_paper_splitter.figures import FigureExtractor, recurring_xrefs  # noqa: E402
from physics_paper_splitter.lines import extract_line_inventory  # noqa: E402
from physics_paper_splitter.models import DocumentInspection  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts._verify_answer_figure_reuse import rebuild_records, trailing_number  # noqa: E402


def main() -> int:
    extract_path = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2])
    qpc = int(sys.argv[3])

    data = json.loads(extract_path.read_text(encoding="utf-8"))
    backup = extract_path.with_name("extract.prev.json")
    shutil.copyfile(extract_path, backup)
    print(f"已留档 {backup.name}")

    items = data["items"]
    figures_dir = extract_path.parent / "figures"
    doc = fitz.open(pdf_path)

    # ── 1. 重放答案归一 ──────────────────────────────────────────────
    inspection = DocumentInspection(
        pdf_path=pdf_path,
        page_count=len(doc),
        question_page_count=qpc,
        answer_start_page=qpc + 1,
        pages=[],
    )
    regex_by_number = parse_answers(doc, inspection)["questions"]
    labels = [(it["qid"], it.get("label"), it.get("section")) for it in items]
    llm_entries = [
        {
            "label": src.get("label") or it.get("label"),
            "answer": src.get("answer"),
            "explanation": src.get("explanation"),
        }
        for it in items
        for src in (it.get("answer_sources") or [])
        if src.get("origin") != "answer_key_regex"
    ]
    resolved, _warnings = resolve_answers(
        labels, [], inline_texts={},
        answer_key_llm=llm_entries, answer_key_regex=regex_by_number,
    )
    by_qid = {r.qid: r for r in resolved}

    answer_changed = 0
    for it in items:
        result = by_qid.get(it["qid"])
        if result is None:
            continue
        old_answer = it.get("answer")
        new_sources = [e.to_dict() for e in result.evidences]
        changed = (
            (old_answer or "") != (result.answer or "")
            or bool(it.get("answer_conflict")) != bool(result.conflict)
            or it.get("answer_origin") != result.origin
            or new_sources != (it.get("answer_sources") or [])
        )
        if not changed:
            continue
        answer_changed += 1
        print(
            f"[答案] 第{it.get('question_number')}题 "
            f"{(old_answer or '')[:36]!r} -> {(result.answer or '')[:36]!r} "
            f"conflict {bool(it.get('answer_conflict'))} -> {bool(result.conflict)}"
        )
        it["answer"] = result.answer
        it["answer_origin"] = result.origin
        it["answer_conflict"] = bool(result.conflict)
        it["answer_note"] = result.note
        it["answer_sources"] = new_sources
        if not result.answer and old_answer:
            # 「缺答案比错答案好」的另一面：答案被清空时必须进人工核对。
            it["needs_review"] = True

    # ── 2. 重放答案区取图（near/far 新口径）──────────────────────────
    records = rebuild_records(items)
    extractor = FigureExtractor()
    detailed = extractor.plan_ownership_with_xrefs(doc, records, recurring=recurring_xrefs(doc))
    number_by_qid = {
        int(it["qid"]): n
        for it in items
        if (n := trailing_number(it.get("label") or "")) is not None
    }
    counts = Counter(number_by_qid.values())
    stem_xrefs: dict[int, set[int]] = {}
    stem_names: dict[int, dict[int, str]] = {}
    stem_indexes: dict[int, dict[int, int]] = {}
    for qid, number in number_by_qid.items():
        if counts[number] != 1:
            continue
        pairs = detailed.get(qid, [])
        if not pairs:
            continue
        stem_xrefs[number] = {xref for _p, _r, xref in pairs}
        stem_names[number] = {xref: f"figures/Q{qid:03d}_{i:02d}.webp" for i, (_p, _r, xref) in enumerate(pairs, 1)}
        stem_indexes[number] = {xref: i for i, (_p, _r, xref) in enumerate(pairs, 1)}

    wanted = {
        number_by_qid[int(it["qid"])]
        for it in items
        if int(it["qid"]) in number_by_qid
        and answer_needs_figures(it.get("answer"), bool(it.get("answer_sources")))
    }
    answer_lines = extract_line_inventory(doc, range(qpc, doc.page_count))
    plans, reused = plan_answer_figures(doc, answer_lines, wanted, stem_xrefs=stem_xrefs)
    kept = extract_answer_figures(doc, plans, figures_dir)

    stale_files: list[Path] = []
    for it in items:
        number = number_by_qid.get(int(it["qid"]))
        old = list(it.get("answer_figures") or [])
        new = kept.get(number, []) if number is not None else []
        if old == new:
            continue
        print(f"[取图] 第{it.get('question_number')}题 {len(old)} -> {len(new)} 张: {new}")
        for path in old:
            if path not in new:
                stale_files.append(figures_dir.parent / path)
        it["answer_figures"] = new
    for path in stale_files:
        if path.exists() and path.name.startswith("answer_Q"):
            path.unlink()
            print(f"  清掉不再被引用的 {path.name}")

    refs = plan_stem_figure_refs(reused, kept, stem_names, stem_indexes)
    for it in items:
        number = number_by_qid.get(int(it["qid"]))
        new_refs = refs.get(number, []) if number is not None else []
        if (it.get("answer_figure_refs") or []) != new_refs:
            print(f"[引用] 第{it.get('question_number')}题 answer_figure_refs -> {new_refs}")
            it["answer_figure_refs"] = new_refs

    # ── 3. answer_blocks 小问分块 ────────────────────────────────────
    for it in items:
        number = number_by_qid.get(int(it["qid"]))
        figures = kept.get(number, []) if number is not None else []
        blocks = split_answer_blocks(it.get("answer"))
        if any(block["label"] for block in blocks):
            assign_answer_figures(blocks, figures)
        else:
            blocks = []
        it["answer_blocks"] = blocks

    # ── 4. 重算 answer_report / audit 匹配数 ────────────────────────
    report = data.get("answer_report") or {}
    by_origin = Counter(it["answer_origin"] for it in items if it.get("answer") and it.get("answer_origin"))
    matched = sum(1 for it in items if it.get("answer"))
    conflicts = sorted(it["question_number"] for it in items if it.get("answer_conflict"))
    unmatched = sorted(it["question_number"] for it in items if not it.get("answer"))
    report.update(
        {
            "total": len(items),
            "matched": matched,
            "match_ratio": round(matched / len(items), 4) if items else 0.0,
            "by_origin": dict(by_origin),
            "conflicts": conflicts,
            "unmatched": unmatched,
        }
    )
    data["answer_report"] = report
    audit = data.get("audit") or {}
    if audit:
        audit["answer_matched"] = matched
        audit["answer_total"] = len(items)

    extract_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\n写回完成：答案变化 {answer_changed} 题 / 冲突 {conflicts} / "
        f"答案图 {[ (n, len(kept.get(n, []))) for n in sorted(kept) ]}"
    )
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
