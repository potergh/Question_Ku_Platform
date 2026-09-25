"""``scripts/golden_extract.py`` 验收判定的回归测试（离线，不调 VLM）。

锁住两条被真实跑测打脸过的行为：

1. **零切出必须判失败。** ``audit.coverage_ratio`` 在 ``total_lines == 0`` 时
   保持默认值 ``1.0``，其余检查项又全都走「无标记，跳过」，导致一份切出
   0 题的扫描件覆盖率 100%、无孤儿页、判定 PASS、退出码 0。
2. **随堂检测被标成纯序号也算切出。** 讲义实测里随堂题全被标成「1、」…
   「19、」，旧正则只认「随堂」二字，把已切出的 39 题误判为 0 题，讲义
   因此被判 FAIL。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(BACKEND_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import golden_extract as g  # noqa: E402


def _item(label: str, raw_text: str = "", answer: str | None = None):
    return SimpleNamespace(
        label=label, excluded=False, raw_text=raw_text, answer=answer
    )


def _result(*, question_count: int, audit: dict, items: list):
    return SimpleNamespace(
        audit=audit,
        items=items,
        doc_kind="handout",
        question_count=question_count,
        review_count=0,
        output_dir="",
    )


def _checks(report) -> dict[str, bool]:
    return {name: ok for name, ok, _ in report.checks}


def test_zero_cut_is_failed_despite_perfect_coverage():
    """0 题 + 覆盖率 100% + 无孤儿页，仍必须判 FAIL。"""
    result = _result(
        question_count=0,
        audit={
            "coverage_ratio": 1.0,
            "total_lines": 0,
            "lost_chars": 0,
            "orphan_pages": [],
            "blocked": True,
            "reasons": ["没有切出任何题目。"],
        },
        items=[],
    )
    report = g.build_report(Path("scan.pdf"), result, g.SourceMarkers(pages=10))

    checks = _checks(report)
    assert report.passed is False
    assert checks["切出题数>0"] is False
    assert checks["审计闸门放行"] is False
    # 这三条正是旧版误判 PASS 的来源：它们在零切出时全是「好数字」。
    assert checks["覆盖率≥95%"] is True
    assert checks["无孤儿页"] is True


def test_numbered_labels_count_as_second_numbering_system():
    """随堂检测被标成「1、」这类纯序号时，也要算作第二套编号已切出。"""
    items = [f"【例{i}】" for i in range(1, 37)] + [f"{i}、" for i in range(1, 40)]
    result = _result(
        question_count=75,
        audit={
            "coverage_ratio": 1.0,
            "lost_chars": 0,
            "orphan_pages": [],
            "blocked": False,
            "reasons": [],
        },
        items=[_item(label) for label in items],
    )
    markers = g.SourceMarkers(pages=25, examples=36, inline_answers=75, suizang_blocks=2)
    report = g.build_report(Path("handout.pdf"), result, markers)

    assert report.example_cut == 36
    assert report.suizang_cut == 39
    assert report.passed is True


@pytest.mark.parametrize(
    "label",
    ["1、", "2.", "3．", "12）", "随堂检测-1", "随堂检测 2"],
)
def test_second_numbering_label_forms_are_recognized(label):
    """两种编号形式都要认：显式带「随堂」，或不带前缀的纯序号。"""
    assert g.SUIZANG_LABEL_RE.search(label) or g.NUMBERED_LABEL_RE.match(label)


def test_example_label_is_not_counted_as_numbered():
    """「【例1】」不能同时被算进第二套编号，否则两套编号检查会永远通过。"""
    assert g.NUMBERED_LABEL_RE.match("【例1】") is None
