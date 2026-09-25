r"""golden 定版前的题干自检：逐题看首行是不是本题题号。

为什么需要它：Q22 的题干首行被划进上一题，题干从半句话开始，靠人工对着
截图才发现。这类错误有个确定性的指纹——**题卡的首行不是本题题号**。
本脚本零模型成本、不需要 boundary_spans，对任意产物目录都能跑，
是定版前最后一道自检。

用法（项目根目录）::

    venv/Scripts/python.exe backend/scripts/_audit_golden_stems.py "<产物目录名>"
    venv/Scripts/python.exe backend/scripts/_audit_golden_stems.py "<产物目录名>" --show 8

判据与已知误报：
- 首行匹配「题号」用 `STEM_NUMBER_RE`（前缀最多 4 个非数字 + 数字 + 分隔符），
  形状脱胎于 audit.py 的 LEADING_NUMBER_RE。「（2）」「D．4.5m」这类小问编号与
  选项标签也会被正则命中 —— 所以**只看首行**（题卡首行本该是题号），
  不看末行：末行是小问或选项完全正常，照末行判会满屏误报。
- 「(多选) 13.（3 分）…」这类行首标注会挤掉题号前缀的名额（`(多选) ` 是 5 个
  非数字字符，超过 `\D{0,4}`）→ 判题号前先剥掉「(多选) / （单选）/ (不定项)」。
  这条是扫 `__before_fix` 时发现的：Q39（label='13．'）首行是
  '(多选) 13.（3 分）…'，内容完全正确，是脚本自己的误报。
- 选择题（首行是题干）与综合题（首行是「21．（7 分）…」）都能覆盖。
- 判据用 `STEM_NUMBER_RE`，**不是** audit.py 的 `LEADING_NUMBER_RE`：后者把 `）)` 也
  当题号分隔符，于是小问编号「（1）」会被认成题号「1」。后果是第 1 题的题干若被切成
  从「（1）求电源电压」开始，恰好对上题号 1 → **漏报**。本脚本的分隔符只收
  `．.、】`，把这种漏报堵上（这条盲点是单元测试跑出来的，不是拍脑袋加的）。
  代价：题号本身写成「13）」的卷会误报 —— 三份 golden 的 label 分隔符统计是
  `．`(51) / `】`(36) / `、`(39)，没有 `）`，暂未遇到。

退出码：0 = 全部通过；2 = 有题首行不像本题题号。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OCR = ROOT / "data/ocr_output"

# 形状脱胎于 physics_paper_splitter.audit.LEADING_NUMBER_RE（前缀最多 4 个非数字
# + 数字 + 分隔符），但**分隔符刻意不收 `）)`**：
#   audit 那边要认小问编号，所以 `）)` 也算；本脚本要抓的恰恰是「首行变成了小问编号」，
#   照搬会漏报。本脚本刻意保持零依赖不 import audit，代价是**改那边时要回来看一眼**。
# 收 `】` 是为了讲义的「【例1】」。
STEM_NUMBER_RE = re.compile(r"^\D{0,4}?(\d{1,3})\s*[．.、】]")

# 已知失配：「(多选) 13.（3 分）…」——`(多选) ` 是 5 个非数字字符，超过上面 \D{0,4}
# 的上限，首行明明是题号却判成不像。多选标注会写进 label 之外的行首，先剥掉再判。
CHOICE_MARK_RE = re.compile(r"^\s*[（(]\s*(?:多选|单选|不定项)\s*[)）]\s*")


def _strip_choice_mark(line: str) -> str:
    """剥掉行首的「(多选) 」这类标注——它不属于题号，却会挤掉题号正则的前缀名额。"""
    return CHOICE_MARK_RE.sub("", line, count=1)


def _label_number(label: str | None) -> int | None:
    match = re.search(r"\d+", label or "")
    return int(match.group(0)) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description="题干首行题号自检")
    parser.add_argument("document", help="产物目录名，如 2022年…一模试卷__golden")
    parser.add_argument("--show", type=int, default=6, help="最多打印多少条异常")
    args = parser.parse_args()

    extract_path = (OCR / args.document).resolve() / "extract.json"
    if not extract_path.exists():
        print(f"[FAIL] 找不到产物：{extract_path}")
        return 2
    doc = json.loads(extract_path.read_text(encoding="utf-8"))
    items = [item for item in doc.get("items", []) if not item.get("excluded")]
    if not items:
        print("[FAIL] 产物里没有可用题目")
        return 2

    bad: list[tuple[int, str, str]] = []
    for item in items:
        number = item.get("question_number")
        raw = (item.get("raw_text") or "").strip()
        first = next((line.strip() for line in raw.splitlines() if line.strip()), "")
        if not first:
            bad.append((number, "（空 raw_text）", ""))
            continue
        match = STEM_NUMBER_RE.match(_strip_choice_mark(first))
        expected = _label_number(item.get("label")) or number
        if match is None or int(match.group(1)) != expected:
            bad.append((number, first, item.get("label") or ""))

    print(f"产物：{args.document}")
    print(f"题数 {len(items)} | 首行不像本题题号的：{len(bad)} 题")
    if not bad:
        print("\n✓ 全部通过：每题题卡首行都是本题题号（没有 Q22 那种题干被切）。")
        return 0

    print("\n需要人工核对：")
    for number, head, label in bad[: args.show]:
        print(f"  Q{number}（label={label!r}）首行：{head[:60]!r}")
    if len(bad) > args.show:
        print(f"  … 另有 {len(bad) - args.show} 题")
    print("\n注：续行题、跨页题、表格题的首行可能本就不像题号，报出来不等于错。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
