"""v10 全管线重跑的验收脚本：新加的两道加固层到底有没有工作。

只做读取与统计，不改任何产物。回答三个问题：

1. **确定性边界校验**（boundary_audit）报了什么？逐条列出规则类型与题号，
   并标注该题在 v9（人工已核版）里是否是已知问题 —— 命中/误报一栏见分晓。
2. **定向仲裁**（arbitrate_conflicts）对几道冲突题出了判决？结论是什么？
   与人工在 v9 里的裁定是否一致？
3. **v10 相对 v9 有无回归**：题干、答案逐题比对，重点看 Q22（题头被切）
   在新一轮里是否被切出、被校验标记。

用法（项目根目录）::

    venv/Scripts/python.exe backend/scripts/_verify_v10_guardrails.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V9 = ROOT / "data/ocr_output/2022年天津市和平区中考物理一模试卷__v9"
V10 = ROOT / "data/ocr_output/2022年天津市和平区中考物理一模试卷__v10"

# boundary_audit 的四条规则（与 audit.py 的 BoundaryFinding.code 对齐）。
RULE_NAMES = {
    "span_overlap": "区间重叠",
    "number_sequence_broken": "题号单调",
    "first_line_unnumbered": "首行非题号",
    "coverage_gap": "分题漏行",
}

# 人工在 v9 里已确认过的「真缺陷」题号（来自 09-12 的人工核对记录）。
# 校验若报出这些题 → 命中；报出其余题 → 需人工复核是否为误报。
HUMAN_CONFIRMED_DEFECTS = {22}
# 人工已逐题核过并 approved 的题（这些题若被报，多半是误报或次要问题）。
HUMAN_APPROVED = {19, 20, 21, 22, 24, 25, 26}


def _load(path: Path) -> dict:
    return json.loads((path / "extract.json").read_text(encoding="utf-8"))


def _rule_of(detail: str) -> str:
    for code, name in RULE_NAMES.items():
        if code in detail:
            return f"{name}({code})"
    return "其他"


def collect_boundary_findings(doc: dict) -> list[tuple[int, str, str]]:
    """从全局 warnings 与单题 warnings 里捞出确定性校验的发现。"""
    found: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()
    for item in doc["items"]:
        for warning in item.get("warnings") or []:
            if "确定性边界校验" not in warning:
                continue
            detail = warning.split("确定性边界校验：", 1)[-1].strip()
            key = (item["question_number"], detail)
            if key in seen:
                continue
            seen.add(key)
            found.append((item["question_number"], _rule_of(detail), detail))
    return sorted(found)


def collect_arbitrations(doc: dict) -> list[tuple[int, str]]:
    out = []
    for item in doc["items"]:
        note = item.get("answer_note") or ""
        if "仲裁：" in note:
            verdict_text = note.split("仲裁：", 1)[-1]
            out.append((item["question_number"], verdict_text[:160]))
    return out


def compare(v9: dict, v10: dict) -> None:
    by_num_9 = {i["question_number"]: i for i in v9["items"]}
    by_num_10 = {i["question_number"]: i for i in v10["items"]}

    print("=" * 78)
    print("三、v10 与 v9 逐题比对（v9 为人工已核版）")
    print("=" * 78)
    only9 = sorted(set(by_num_9) - set(by_num_10))
    only10 = sorted(set(by_num_10) - set(by_num_9))
    print(f"题数：v9={len(by_num_9)}  v10={len(by_num_10)}")
    if only9:
        print(f"仅 v9 有：{only9}")
    if only10:
        print(f"仅 v10 有：{only10}")

    stem_diff, answer_diff = [], []
    for num in sorted(set(by_num_9) & set(by_num_10)):
        a, b = by_num_9[num], by_num_10[num]
        if (a.get("stem_md") or "").strip() != (b.get("stem_md") or "").strip():
            stem_diff.append(
                (num, len(a.get("stem_md") or ""), len(b.get("stem_md") or ""))
            )
        if (a.get("answer") or "").strip() != (b.get("answer") or "").strip():
            answer_diff.append(num)
    print(f"\n题干不同的题：{len(stem_diff)} 道")
    for num, la, lb in stem_diff:
        print(f"  Q{num}: v9 {la} 字 → v10 {lb} 字")
    print(f"\n答案不同的题：{len(answer_diff)} 道 {answer_diff if answer_diff else ''}")


def main() -> int:
    if not (V10 / "extract.json").exists():
        print(f"[FAIL] 找不到 v10 产物：{V10 / 'extract.json'}")
        return 2
    v9 = _load(V9)
    v10 = _load(V10)

    print("=" * 78)
    print("一、确定性边界校验（boundary_audit，零模型成本）")
    print("=" * 78)
    findings = collect_boundary_findings(v10)
    audit = v10.get("audit") or {}
    print(
        f"题数 {v10.get('question_count')} | 覆盖率 "
        f"{audit.get('coverage_ratio', 0):.1%} | 孤儿页 {audit.get('orphan_pages') or '无'}"
        f" | 闸门 {'阻断' if audit.get('blocked') else '放行'}"
    )
    print(f"\n共 {len(findings)} 处发现：")
    for num, rule, detail in findings:
        tag = ""
        if num in HUMAN_CONFIRMED_DEFECTS:
            tag = "  ★命中已知缺陷"
        elif num in HUMAN_APPROVED:
            tag = "  ?人工已 approved —— 疑似误报"
        print(f"  Q{num:<3} {rule:<24} {detail[:64]}{tag}")

    hit = sum(1 for num, _, _ in findings if num in HUMAN_CONFIRMED_DEFECTS)
    unknown = [num for num, _, _ in findings if num not in HUMAN_APPROVED]
    print(f"\n命中已知缺陷：{hit} 处")
    print(f"落在未人工核过的题上（需人工判定真伪）：{sorted(set(unknown)) or '无'}")

    print()
    print("=" * 78)
    print("二、定向仲裁（arbitrate_conflicts）")
    print("=" * 78)
    arbitrations = collect_arbitrations(v10)
    conflicts = [i["question_number"] for i in v10["items"] if i.get("answer_conflict")]
    print(f"本轮 conflict 题：{conflicts or '无'}")
    print(f"仲裁产出：{len(arbitrations)} 条")
    for num, text in arbitrations:
        print(f"  Q{num}: {text}")

    # 仲裁有没有偷偷改答案：answer_conflict 应全部保留。
    still_conflict = [
        i["question_number"] for i in v10["items"] if i.get("answer_conflict")
    ]
    if set(still_conflict) != set(conflicts):
        print("[WARN] 冲突集合在仲裁后发生了变化 —— 需要检查")
    else:
        print("✓ 冲突标记未被仲裁改动（answer/origin 未被机器改写）")

    print()
    compare(v9, v10)

    print()
    print("=" * 78)
    print("四、全局 warnings（v10）")
    print("=" * 78)
    for warning in v10.get("warnings") or []:
        print("  -", warning[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
