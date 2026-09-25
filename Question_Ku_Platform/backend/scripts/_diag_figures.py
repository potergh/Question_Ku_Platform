"""零成本复算：用已保存的 segments 重跑插图归属，对比修复前后。

不调用任何模型 —— 只读 extract.json 里的 segments 与 PDF，重放 FigureExtractor。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

from physics_paper_splitter.figures import FigureExtractor  # noqa: E402
from physics_paper_splitter.models import CropSegment, QuestionRecord  # noqa: E402

OUT = ROOT / "data/ocr_output/2022年天津市和平区中考物理一模试卷__golden"
PDF = ROOT / "test_data/2022年天津市和平区中考物理一模试卷.pdf"
TMP = ROOT / "data/ocr_output/_diag_figures_tmp"


def main() -> None:
    data = json.loads((OUT / "extract.json").read_text(encoding="utf-8"))
    doc = fitz.open(PDF)

    records: list[QuestionRecord] = []
    old_counts: dict[int, int] = {}
    for item in data["items"]:
        number = item.get("question_number") or item["qid"]
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
        records.append(
            QuestionRecord(
                number=number,
                filename=f"Q{number}.png",
                start_page=item.get("start_page") or 0,
                end_page=item.get("end_page") or 0,
                is_cross_page=bool(item.get("is_cross_page")),
                segments=segments,
            )
        )
        old_counts[number] = len(item.get("figures") or [])

    if TMP.exists():
        shutil.rmtree(TMP)
    extractor = FigureExtractor()
    new_map = extractor.extract_all(doc, records, TMP)
    doc.close()

    old_total = sum(old_counts.values())
    new_total = sum(len(v) for v in new_map.values())
    print(f"修复前：{old_total} 张，平均 {old_total / len(records):.1f} 张/题")
    print(f"修复后：{new_total} 张，平均 {new_total / len(records):.1f} 张/题")
    print(f"丢弃空白装饰图：{extractor.last_blank_dropped}")
    print(f"跨题重复已归一：{extractor.last_shared_reassigned}")
    print()

    print("逐题张数（旧 -> 新）：")
    for record in records:
        new_n = len(new_map.get(record.number, []))
        mark = "" if new_n == old_counts[record.number] else "  <-"
        print(f"  Q{record.number:03d}: {old_counts[record.number]:2d} -> {new_n:2d}{mark}")

    # 同一张图是否仍被多题共用
    owner: dict[str, list[int]] = {}
    for number, paths in new_map.items():
        for path in paths:
            digest = hashlib.md5((TMP / Path(path).name).read_bytes()).hexdigest()
            owner.setdefault(digest, []).append(number)
    shared = {d: ns for d, ns in owner.items() if len(ns) > 1}
    print()
    print(f"修复后仍被多题共用的图：{len(shared)} 张")
    for digest, numbers in list(shared.items())[:5]:
        print(f"  {digest[:10]} -> {sorted(numbers)}")


if __name__ == "__main__":
    main()
