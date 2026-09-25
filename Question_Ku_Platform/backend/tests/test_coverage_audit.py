"""覆盖率审计闸门的回归测试。

用几何自洽的假数据构造已知覆盖率：行的 y 与题卡片段的 [y0, y1] 对齐，
覆盖窗口为 [y0 - TOLERANCE_PT, y1 + TOLERANCE_PT]（TOLERANCE_PT = 6）。

基线数字取自真实文档实测评：讲义 42.6% 必须阻断（远低于 95% 闸门）；
试卷 98% 覆盖（≥ 95% 闸门）必须放行。分数避开了 4 位浮点半值
（banker's rounding），断言不会飘。
"""

from __future__ import annotations

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from physics_paper_splitter.audit import coverage_audit, item_flags
from physics_paper_splitter.lines import TextLine
from physics_paper_splitter.models import CropSegment, QuestionRecord

FIRST_Y0 = 60.0
LINE_GAP = 25.0
LINE_HEIGHT = 12.0


def _lines(per_page: dict[int, int]) -> list[TextLine]:
    """按 {页索引: 行数} 造行清单；line_id 从 1 起按页序递增。

    第 i 行（页内 0-based）的 y0 = 60 + 25*i，y1 = y0 + 12。
    """
    lines: list[TextLine] = []
    line_id = 0
    for page in sorted(per_page):
        for index in range(per_page[page]):
            line_id += 1
            y0 = FIRST_Y0 + LINE_GAP * index
            lines.append(
                TextLine(
                    line_id=line_id,
                    page_index=page,
                    y0=y0,
                    y1=y0 + LINE_HEIGHT,
                    x0=40.0,
                    x1=520.0,
                    text=f"第{line_id}行正文",
                )
            )
    return lines


def _record(page: int, covered: int) -> QuestionRecord:
    """造一张覆盖到该页第 covered 行的题卡。

    片段 y0 固定为 50（= FIRST_Y0 - 10），y1 = 25*covered + 45，
    覆盖窗口 [44, y1 + 6] 恰好命中前 covered 行、漏掉第 covered+1 行。
    """
    return QuestionRecord(
        number=1,
        filename="Q001.webp",
        start_page=page + 1,
        end_page=page + 1,
        is_cross_page=False,
        segments=[
            CropSegment(
                page_index=page,
                x0=40.0,
                y0=50.0,
                x1=520.0,
                y1=LINE_GAP * covered + 45.0,
            )
        ],
    )


def test_handout_coverage_blocks():
    """讲义场景：12 页大量内容没进题卡 -> 覆盖率 42.6%，必须阻断。"""
    per_page = {page: 10 for page in range(7)}  # 0-6 页各 10 行 = 70
    per_page.update({page: 9 for page in range(7, 12)})  # 7-11 页各 9 行 = 45
    lines = _lines(per_page)  # 共 115 行

    records = [_record(page, 10) for page in range(4)]  # 0-3 页各覆盖 10 行 = 40
    records.append(_record(4, 9))  # 第 4 页覆盖 9 行
    # 覆盖 49 / 115

    report = coverage_audit(lines, records, 12)

    assert report.total_lines == 115
    assert report.covered_lines == 49
    assert report.coverage_ratio == 0.4261
    assert report.blocked is True
    # 5-11 页（0-based）完全没有题卡 -> 1-based 6..12
    assert report.orphan_pages == [6, 7, 8, 9, 10, 11, 12]
    assert any("覆盖率" in reason for reason in report.reasons)
    assert any("完全没有题卡" in reason for reason in report.reasons)


def test_paper_coverage_passes():
    """试卷场景：覆盖 98%（≥ 95% 闸门），且无孤儿页 -> 放行。"""
    per_page = {page: 10 for page in range(10)}  # 0-9 页各 10 行 = 100
    lines = _lines(per_page)

    records = [_record(page, 10) for page in range(9)]  # 0-8 页全覆盖 = 90
    records.append(_record(9, 8))  # 第 9 页漏 2 行
    # 覆盖 98 / 100

    report = coverage_audit(lines, records, 10)

    assert report.total_lines == 100
    assert report.covered_lines == 98
    assert report.coverage_ratio == 0.98
    assert report.blocked is False
    assert report.orphan_pages == []
    assert report.reasons == []


def test_no_records_blocks():
    lines = _lines({0: 3})
    report = coverage_audit(lines, [], 1)

    assert report.covered_lines == 0
    assert report.blocked is True
    assert report.orphan_pages == [1]
    assert any("没有切出任何题目" in reason for reason in report.reasons)


def test_answer_floor_blocks():
    """覆盖没问题，但答案匹配率 70% < 80% -> 同样阻断。"""
    lines = _lines({0: 2})
    report = coverage_audit(lines, [_record(0, 2)], 1, answer_total=10, answer_matched=7)

    assert report.coverage_ratio == 1.0
    assert report.answer_match_ratio == 0.7
    assert report.blocked is True
    assert any("答案匹配率" in reason for reason in report.reasons)


def test_answer_floor_skipped_without_answer_source():
    """纯题目卷本就不带答案：没有答案源时不得阻断，否则永远无法入库。

    实测 2026 河东一模（10 页扫描件、无答案区）因此被 0/25 拦死。
    """
    lines = _lines({0: 2})
    report = coverage_audit(
        lines,
        [_record(0, 2)],
        1,
        answer_total=25,
        answer_matched=0,
        answer_applicable=False,
    )

    # 数字照常记录，只是不算比率、不阻断。
    assert report.answer_total == 25
    assert report.answer_matched == 0
    assert report.answer_match_ratio is None
    assert report.blocked is False
    assert not any("答案匹配率" in reason for reason in report.reasons)


def test_answer_floor_still_blocks_when_source_exists():
    """有答案源时必须照常严格，不能因为放宽了上一档就整体失效。"""
    lines = _lines({0: 2})
    report = coverage_audit(
        lines,
        [_record(0, 2)],
        1,
        answer_total=25,
        answer_matched=0,
        answer_applicable=True,
    )

    assert report.answer_match_ratio == 0.0
    assert report.blocked is True
    assert any("答案匹配率" in reason for reason in report.reasons)


def test_excluded_lines_leave_the_denominator():
    """非题目区域的行不计入覆盖率分母，不应误伤通过判定。"""
    lines = _lines({0: 4})
    report = coverage_audit(
        lines, [_record(0, 2)], 1, excluded_line_ids={3, 4}
    )

    assert report.total_lines == 2
    assert report.excluded_lines == 2
    assert report.covered_lines == 2
    assert report.coverage_ratio == 1.0
    assert report.orphan_pages == []
    assert report.blocked is False


def test_item_flags_reports_each_condition():
    record = QuestionRecord(
        number=1,
        filename="Q001.webp",
        start_page=1,
        end_page=2,
        is_cross_page=True,
        segments=[CropSegment(page_index=0, x0=0.0, y0=0.0, x1=595.0, y1=800.0)],
        height_px=9500,
    )
    flags = item_flags(record, has_answer=False, has_formula=True, figure_count=2)

    assert set(flags) == {"no_answer", "cross_page", "tall_card", "has_formula", "figures:2"}


def test_item_flags_flags_missing_segments():
    record = QuestionRecord(
        number=1,
        filename="Q001.webp",
        start_page=1,
        end_page=1,
        is_cross_page=False,
        segments=[],
    )
    assert item_flags(record, has_answer=True) == ["no_segments"]


def test_lost_lines_are_sampled_for_human_triage():
    """只报「丢了 76 字」没法行动，得知道丢的是哪几行。

    实测河东卷覆盖率 99.1%（放行）但丢了 2 行 76 字 —— 不知道内容就无法判断
    那是页脚说明还是真题干。
    """
    lines = [
        TextLine(line_id=1, page_index=0, y0=100.0, y1=112.0, x0=0.0, x1=100.0, text="第1题"),
        TextLine(line_id=2, page_index=2, y0=300.0, y1=312.0, x0=0.0, x1=100.0, text="被漏掉的题干"),
    ]
    record = QuestionRecord(
        number=1,
        filename="Q001.webp",
        start_page=1,
        end_page=1,
        is_cross_page=False,
        segments=[CropSegment(page_index=0, x0=0.0, y0=90.0, x1=595.0, y1=120.0)],
    )
    report = coverage_audit(lines, [record], page_count=3, coverage_floor=0.5)
    assert report.lost_chars == len("被漏掉的题干")
    assert report.lost_samples and report.lost_samples[0]["page"] == 3
    assert report.lost_samples[0]["text"] == "被漏掉的题干"
