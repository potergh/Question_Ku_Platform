"""修复和平卷 Q21/Q22 卡片分界：Q22 题干首行被切掉（2026-09-12 人工发现）。

根因：PyMuPDF 把「22．（6 分）如图所示电路中…都闭合」一行的 bbox 合并成了
y=453-511（横跨 Q21(2) 与 Q22 首行两个视觉行），边界模型按渲染图切分时把
Q22 的 y0 定在 495.62 —— 正好切在 Q22 第一、二行之间；同时 Q21 的 y1=515.31
把 Q22 前两行包进了自己的卡。

修法（离线、确定性）：分界线定在 y=468（Q21(2) 行止于 465，Q22 首行起于
约 474），重裁两张卡；Q22 的 stem_md/content/raw_text 补回缺失的首行；
Q21 的 raw_text 去掉串进来的 Q22 首行；题库表同步。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "packages"))

import pymupdf as fitz  # noqa: E402

from physics_paper_splitter.cropper import QuestionCropper  # noqa: E402
from physics_paper_splitter.models import CropSegment, QuestionRecord  # noqa: E402

Q21_LEAD = "22．（6 分）如图所示电路中，小灯泡L 标有“6V 6W”字样，R2＝14Ω，当S1、S2 都闭合"
STEM_LEAD = (
    "如图所示电路中，小灯泡 $L$ 标有“6V 6W”字样，$R_2 = 14\\,\\Omega$，"
    "当 $S_1$、$S_2$ 都闭合"
)
SPLIT_Y = 468.0


def main() -> int:
    extract_path = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2])
    db_path = ROOT / "data" / "db.sqlite3"

    shutil.copyfile(extract_path, extract_path.with_name("extract.prev2.json"))
    data = json.loads(extract_path.read_text(encoding="utf-8"))
    items = {it["question_number"]: it for it in data["items"]}

    q21, q22 = items[21], items[22]

    # 1. 分界线：Q21 止于 468，Q22 起于 468。
    assert q21["segments"][0]["y1"] > SPLIT_Y and q22["segments"][0]["y0"] > SPLIT_Y
    q21["segments"][0]["y1"] = SPLIT_Y
    q22["segments"][0]["y0"] = SPLIT_Y

    # 2. Q22 题干补回首行。
    for field in ("stem_md", "content"):
        text = q22.get(field) or ""
        if text.startswith(STEM_LEAD[:12]):
            continue
        q22[field] = STEM_LEAD + text
    if not (q22.get("raw_text") or "").startswith("22．"):
        q22["raw_text"] = Q21_LEAD + "\n" + (q22.get("raw_text") or "")

    # 3. Q21 raw_text 去掉串进来的 Q22 首行。
    raw = q21.get("raw_text") or ""
    if raw.endswith(Q21_LEAD):
        q21["raw_text"] = raw[: -len(Q21_LEAD)].rstrip()

    # 4. 重裁两张卡（与管线同一 QuestionCropper 参数）。
    doc = fitz.open(pdf_path)
    cropper = QuestionCropper()
    questions_dir = extract_path.parent / "questions"
    for number, item in ((21, q21), (22, q22)):
        record = QuestionRecord(
            number=number,
            filename=f"Q{number:03d}.webp",
            start_page=item["start_page"],
            end_page=item["end_page"],
            is_cross_page=bool(item.get("is_cross_page")),
            segments=[CropSegment(**seg) for seg in item["segments"]],
            label=item.get("label") or "",
        )
        path = cropper.crop(doc, record, questions_dir)
        item["width_px"], item["height_px"] = record.width_px, record.height_px
        print(f"重裁 {path.name}: {record.width_px}x{record.height_px}")

    extract_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 5. 题库表同步（已落库的行）。
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            for number, item in ((21, q21), (22, q22)):
                cur = conn.execute(
                    "UPDATE questions SET content=?, raw_ocr_content=? "
                    "WHERE question_number=? AND content LIKE ? AND is_deleted=0",
                    (
                        item.get("content"),
                        item.get("raw_text"),
                        number,
                        ("时，电流表示数%" if number == 22 else "%额定电压下，加热棒每次工作的时间%"),
                    ),
                )
                if cur.rowcount:
                    print(f"题库第 {number} 题已同步（{cur.rowcount} 行）")
            conn.commit()
        finally:
            conn.close()
    doc.close()
    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
