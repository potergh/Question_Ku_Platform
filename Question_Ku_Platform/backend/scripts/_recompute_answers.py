"""离线重算答案（不调用任何模型），用于预览答案归一改动后的效果。

重放真实的 `resolve_answers`：regex 路用 parse_answers 现算，其余证据沿用
产物里已存的 answer_sources。归一/守卫/冲突判定改动后这里自动跟上 ——
之前的简化版自己拼 next()+distinct，详略守卫这类新逻辑就跑不到。

用法：
    ../venv/Scripts/python.exe scripts/_recompute_answers.py <extract.json> <pdf> <question_page_count>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "packages"))

import pymupdf as fitz  # noqa: E402

from app.services.api_extract.answers import resolve_answers  # noqa: E402
from physics_paper_splitter.answers import parse_answers  # noqa: E402
from physics_paper_splitter.models import DocumentInspection  # noqa: E402


def main() -> int:
    extract_path = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2])
    question_page_count = int(sys.argv[3])

    data = json.loads(extract_path.read_text(encoding="utf-8"))

    doc = fitz.open(pdf_path)
    inspection = DocumentInspection(
        pdf_path=pdf_path,
        page_count=len(doc),
        question_page_count=question_page_count,
        answer_start_page=question_page_count + 1,
        pages=[],
    )
    regex_by_number = parse_answers(doc, inspection)["questions"]

    items = data.get("items", [])
    # 直接重放 resolve_answers —— 归一/守卫/冲突判定改了这里自动跟上。
    # 之前的简化版自己拼 next()+distinct，归一逻辑一变它就失真（这次
    # 详略守卫就没被它跑到）。产物里没有 inline 证据，非 regex 源全部
    # 从 answer_key_llm 入参回填（本工具只服务文末答案区卷型）。
    labels = [
        (item["qid"], item.get("label"), item.get("section"))
        for item in items
    ]
    llm_entries = [
        {
            "label": source.get("label") or item.get("label"),
            "answer": source.get("answer"),
            "explanation": source.get("explanation"),
        }
        for item in items
        for source in (item.get("answer_sources") or [])
        if source.get("origin") != "answer_key_regex"
    ]

    resolved, _warnings = resolve_answers(
        labels,
        [],
        inline_texts={},
        answer_key_llm=llm_entries,
        answer_key_regex=regex_by_number,
    )
    new_by_qid = {r.qid: r for r in resolved}

    changed: list[tuple] = []
    new_conflicts: set[int] = set()
    old_conflicts: set[int] = set()

    for item in items:
        number = item.get("question_number")
        result = new_by_qid.get(item["qid"])
        new_answer = result.answer if result else None
        is_conflict = bool(result.conflict) if result else False

        old_answer = item.get("answer")
        if (old_answer or "") != (new_answer or "") or bool(item.get("answer_conflict")) != is_conflict:
            changed.append((number, old_answer, new_answer, item.get("answer_conflict"), is_conflict))
        if item.get("answer_conflict"):
            old_conflicts.add(number)
        if is_conflict:
            new_conflicts.add(number)

    print("=" * 78)
    print("答案有变化的题：")
    for number, old, new, old_c, new_c in changed:
        print(f"\n第 {number} 题")
        print(f"  旧: {old!r}")
        print(f"  新: {new!r}")
        if old_c != new_c:
            print(f"  冲突: {old_c} -> {new_c}")
    print()
    print(f"变化 {len(changed)} 题 / 共 {len(items)} 题")
    print(f"冲突题：旧 {sorted(old_conflicts)}")
    print(f"        新 {sorted(new_conflicts)}")
    print(f"        消失 {sorted(old_conflicts - new_conflicts)}")
    print(f"        新增 {sorted(new_conflicts - old_conflicts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
