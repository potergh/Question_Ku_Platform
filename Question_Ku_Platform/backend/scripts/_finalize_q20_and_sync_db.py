"""Q20 答案落图 + DB 与 v9 对齐（golden 定版前的最后一步数据修复）。

背景（人工核对结论，2026-09-12）：
1. Q20 卷面【答案】区（第 28 页）只有电路图、没有文字，答案即该图。按「答案区
   优先取图」规则已裁为 figures/answer_Q020_01.webp，但 answer 字段仍是空，
   audit_flags 还挂着 no_answer，answer_note 还是「未从任何来源找到答案」。
2. Q21 的答案完整抄写修复只写进了 v9 extract.json，没同步进 sqlite（DB 里
   还是 22 字符的旧版）。
3. DB 里全部 26 行的 card_image_path / answer_image_paths 指向 __v9landing
   旧目录：Q021/Q022 题卡是分界修复前的旧裁图，Q20 还挂着两张旧答案图
   （answer_Q020_02 已按新规则废弃）。统一重指到 __v9。

同时把人工已逐题核过的 19/20/21/22/24/25/26 在 DB 里置 review_status=approved。

用法：
    ./venv/Scripts/python.exe backend/scripts/_finalize_q20_and_sync_db.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V9 = ROOT / "data/ocr_output/2022年天津市和平区中考物理一模试卷__v9"
EXTRACT = V9 / "extract.json"
DB = ROOT / "data/db.sqlite3"

Q20_ANSWER = "（卷面答案为电路图，见答案图）"
Q20_NOTE = (
    "卷面【答案】区只有电路图、没有文字（第 28 页），答案即该图，已按「答案区优先」"
    "规则裁为 answer_figures/answer_Q020_01.webp；人工核对确认。"
)
HUMAN_VERIFIED = (19, 20, 21, 22, 24, 25, 26)


def fix_json() -> None:
    data = json.loads(EXTRACT.read_text(encoding="utf-8"))
    q20 = next(x for x in data["items"] if x["question_number"] == 20)

    assert q20.get("answer_figures") == ["figures/answer_Q020_01.webp"], "Q20 答案图异常"
    assert (V9 / "figures/answer_Q020_01.webp").exists(), "Q20 答案图文件缺失"

    shutil.copy2(EXTRACT, EXTRACT.with_name("extract.prev3.json"))

    q20["answer"] = Q20_ANSWER
    q20["answer_note"] = Q20_NOTE
    flags = [f for f in q20.get("audit_flags", []) if f != "no_answer"]
    if "answer_is_figure" not in flags:
        flags.append("answer_is_figure")
    q20["audit_flags"] = flags
    q20["warnings"] = ["卷面答案区无文字，答案为图（answer_figures/answer_Q020_01.webp）"]
    q20["needs_review"] = False
    now = datetime.now().isoformat(timespec="seconds")
    data["updated_at"] = now
    # 管道证据层报告（answer_report/audit）保持原样：它们记录的是管道当时所见，
    # 人工裁定写进 answer_note，不回改报告。

    EXTRACT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[json] Q20 answer/note/flags 已写入，备份 extract.prev3.json")


def fix_db() -> None:
    data = json.loads(EXTRACT.read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB)
    now = datetime.now().isoformat(timespec="seconds")

    # 1) card_image_path / answer_image_paths 全部重指 v9
    for q in data["items"]:
        n = q["question_number"]
        row = conn.execute(
            "select card_image_path, answer_image_paths from questions "
            "where question_number=? and is_deleted=0",
            (n,),
        ).fetchone()
        assert row, f"DB 缺第 {n} 题"
        card = row[0] or ""
        if "__v9landing" in card:
            new_card = card.replace("__v9landing", "__v9")
            assert Path(new_card).exists(), f"Q{n} 新题卡路径不存在: {new_card}"
            conn.execute(
                "update questions set card_image_path=?, updated_at=? "
                "where question_number=? and is_deleted=0",
                (new_card, now, n),
            )
        figs = q.get("answer_figures") or []
        new_imgs = json.dumps([str(V9 / f) for f in figs], ensure_ascii=False) if figs else None
        conn.execute(
            "update questions set answer_image_paths=?, updated_at=? "
            "where question_number=? and is_deleted=0",
            (new_imgs, now, n),
        )

    # 2) Q21 答案补同步 + Q20 答案落库
    for n in (20, 21):
        q = next(x for x in data["items"] if x["question_number"] == n)
        conn.execute(
            "update questions set answer=?, updated_at=? where question_number=? and is_deleted=0",
            (q.get("answer"), now, n),
        )

    # 3) 人工已核过的题置 approved
    for n in HUMAN_VERIFIED:
        conn.execute(
            "update questions set needs_review=0, review_status='approved', updated_at=? "
            "where question_number=? and is_deleted=0",
            (now, n),
        )

    conn.commit()

    # 验证
    bad = []
    for q in data["items"]:
        n = q["question_number"]
        content, answer, card = conn.execute(
            "select content, answer, card_image_path from questions "
            "where question_number=? and is_deleted=0",
            (n,),
        ).fetchone()
        if (content or "").strip() != (q.get("content") or "").strip():
            bad.append((n, "content"))
        if (answer or "").strip() != (q.get("answer") or "").strip():
            bad.append((n, "answer"))
        if "__v9landing" in (card or ""):
            bad.append((n, "card_path"))
    assert not bad, f"同步校验失败: {bad}"
    print("[db] 26 行路径重指 v9，Q20/Q21 答案同步，7 题置 approved —— 全量比对通过")


if __name__ == "__main__":
    fix_json()
    fix_db()
    print("done")
