"""确定性边界校验（boundary_audit）的回归测试。

背景（2026-09-13 用户拍板加入）：覆盖率审计是全卷总账，丢 200 字摊在 26 题
上报表照样全绿；本模块把几何事实下沉到单题粒度。实测动机是第 22 题——
bbox 合并把题干首行划进上一题卡，题干从半句话开始，直到用户人工对着截图
才发现。下列四条规则里，first_line_unnumbered 与 coverage_gap 就是为这类
错误设计的。

用几何自洽的假数据构造：行 y 与题卡片段对齐（TOLERANCE_PT=6），span 的
start_line/end_line 指向行的 line_id。QuestionSpan 从 api_extract.boundary
借入，保持与生产同一类型。
"""

from __future__ import annotations

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from app.services.api_extract.boundary import QuestionSpan
from physics_paper_splitter.audit import boundary_audit
from physics_paper_splitter.lines import TextLine
from physics_paper_splitter.models import CropSegment, QuestionRecord

LINE_GAP = 25.0
LINE_HEIGHT = 12.0


def _lines(texts: list[str]) -> list[TextLine]:
    """按给定文本造行清单，line_id 从 1 起，y0 = 60 + 25*(i-1)。"""
    lines: list[TextLine] = []
    for index, text in enumerate(texts, start=1):
        y0 = 60.0 + LINE_GAP * (index - 1)
        lines.append(
            TextLine(
                line_id=index,
                page_index=0,
                y0=y0,
                y1=y0 + LINE_HEIGHT,
                x0=40.0,
                x1=520.0,
                text=text,
            )
        )
    return lines


def _record(page: int, first_line_y: float, last_line_y: float) -> QuestionRecord:
    """造一张覆盖 [first_line_y, last_line_y] 的单片段题卡。"""
    return QuestionRecord(
        number=0,
        filename="Q000.webp",
        start_page=page + 1,
        end_page=page + 1,
        is_cross_page=False,
        segments=[
            CropSegment(
                page_index=page,
                x0=0.0,
                y0=first_line_y - 6.0,
                x1=595.0,
                y1=last_line_y + LINE_HEIGHT + 6.0,
            )
        ],
    )


def _span(qid: int, label: str, start: int, end: int) -> QuestionSpan:
    return QuestionSpan(
        qid=qid, label=label, section=None, qtype=None, score=None,
        start_line=start, end_line=end,
    )


def test_clean_paper_produces_no_findings():
    """几何自洽 + 题号递增 + 首行带题号 → 零发现。"""
    texts = ["1．（2 分）下列说法正确的是", "A. 甲 B. 乙", "2．（2 分）第二题题干", "A. 丙 B. 丁"]
    lines = _lines(texts)
    records = [
        _record(0, lines[0].y0, lines[1].y0),
        _record(0, lines[2].y0, lines[3].y0),
    ]
    spans = [_span(1, "1．", 1, 2), _span(2, "2．", 3, 4)]
    assert boundary_audit(lines, records, spans) == []


def test_span_overlap_is_flagged():
    """相邻两题行区间重叠 = prompt 契约硬违约。"""
    texts = ["1．第一题题干", "2．第二题题干", "第二题第二行"]
    lines = _lines(texts)
    records = [_record(0, lines[0].y0, lines[1].y0), _record(0, lines[1].y0, lines[2].y0)]
    spans = [_span(1, "1．", 1, 2), _span(2, "2．", 2, 3)]
    kinds = [f.kind for f in boundary_audit(lines, records, spans)]
    assert "span_overlap" in kinds


def test_number_sequence_broken_for_paper():
    """全卷唯一编号时，题号必须按行序递增（试卷形态）。"""
    texts = ["2．第二题先出场", "第二题第二行", "1．第一题后出场", "第一题第二行"]
    lines = _lines(texts)
    records = [
        _record(0, lines[0].y0, lines[1].y0),
        _record(0, lines[2].y0, lines[3].y0),
    ]
    spans = [_span(1, "2．", 1, 2), _span(2, "1．", 3, 4)]
    kinds = [f.kind for f in boundary_audit(lines, records, spans)]
    assert "number_sequence_broken" in kinds


def test_first_line_unnumbered_catches_cut_stem():
    """题头被切：首行从半句话开始（第 22 题事故形态）。"""
    texts = ["1．第一题题干", "1、第一题解析", "时，电流表示数为 0.2A", "2．第二题题干"]
    lines = _lines(texts)
    records = [
        _record(0, lines[0].y0, lines[1].y0),
        _record(0, lines[2].y0, lines[3].y0),
    ]
    spans = [_span(1, "1．", 1, 2), _span(2, "2．", 3, 4)]
    findings = [f for f in boundary_audit(lines, records, spans) if f.qid == 2]
    kinds = [f.kind for f in findings]
    assert "first_line_unnumbered" in kinds


def test_parenthesized_prefix_label_still_matches():
    """「（多选）11．」形态的前缀在 4 字符容差内，不应误报。"""
    texts = ["（多选）11．下列正确的是", "A. 甲 B. 乙", "12．下一题"]
    lines = _lines(texts)
    records = [
        _record(0, lines[0].y0, lines[1].y0),
        _record(0, lines[2].y0, lines[2].y0),
    ]
    spans = [_span(1, "（多选）11．", 1, 2), _span(2, "12．", 3, 3)]
    assert boundary_audit(lines, records, spans) == []


def test_coverage_gap_when_line_outside_card():
    """区间内有行没落进题卡片段（文本与裁图矛盾的 Q22 形态）。"""
    texts = ["1．第一题题干", "1、第一题解析", "2．第二题题干", "2、第二题解析"]
    lines = _lines(texts)
    # 第二张题卡把 y 抬高到 130：第 3 行（y0=110）落在卡外、
    # 第 4 行（y0=135，容差 6 → 判定窗口自 124 起）仍在卡内 → 恰好丢 1 行。
    records = [
        _record(0, lines[0].y0, lines[1].y0),
        QuestionRecord(
            number=2,
            filename="Q002.webp",
            start_page=1,
            end_page=1,
            is_cross_page=False,
            segments=[
                CropSegment(
                    page_index=0,
                    x0=0.0,
                    y0=130.0,
                    x1=595.0,
                    y1=lines[3].y0 + LINE_HEIGHT + 6.0,
                )
            ],
        ),
    ]
    spans = [_span(1, "1．", 1, 2), _span(2, "2．", 3, 4)]
    findings = [f for f in boundary_audit(lines, records, spans) if f.qid == 2]
    kinds = [f.kind for f in findings]
    assert "coverage_gap" in kinds
    gap = next(f for f in findings if f.kind == "coverage_gap")
    assert "1 行" in gap.detail


def test_records_spans_mismatch_is_reported():
    """records 与 spans 数量不一致时给出一条可诊断的发现，而不是崩掉。"""
    lines = _lines(["1．第一题"])
    records = [_record(0, lines[0].y0, lines[0].y0)]
    spans = [_span(1, "1．", 1, 1), _span(2, "2．", 1, 1)]
    findings = boundary_audit(lines, records, spans)
    assert len(findings) == 1
    assert findings[0].kind == "span_record_mismatch"


def test_bracket_label_is_recognized_as_number():
    """讲义的「【例1】」是标准题号写法，不能被判成首行没有编号。

    实测：分隔符正则漏了 】，暑期卷讲义 75 题报出 57 处 first_line_unnumbered，
    其中大量首行就是「【例1】如图所示…」。
    """
    lines = _lines(["【例1】如图所示，甲、乙两个正方体放在水平地面上", "解析内容"])
    records = [_record(0, lines[0].y0, lines[1].y0)]
    spans = [_span(1, "【例1】", 1, 2)]
    findings = boundary_audit(lines, records, spans)
    assert [f.kind for f in findings if f.kind == "first_line_unnumbered"] == []


def test_handout_skips_per_question_rules():
    """讲义形态只跑区间重叠：板块内题号重启、章节标题夹在题目之间、双栏排版
    会让首行题号与分题覆盖两条规则几乎全是误报（暑期卷实测 75 题报 73 处）。"""
    lines = _lines(["二、液体压强", "1．第一题题干", "2．第二题题干"])
    # 区间起点落在章节标题上、题号重复 —— 这两条在讲义里都是正常的。
    records = [_record(0, lines[0].y0, lines[1].y0), _record(0, lines[1].y0, lines[2].y0)]
    spans = [_span(1, "1．", 1, 1), _span(2, "1．", 2, 2)]
    assert boundary_audit(lines, records, spans, doc_kind="handout") == []
    # 同样的输入在试卷形态下会被报出来，证明关掉的是规则而不是数据。
    assert boundary_audit(lines, records, spans, doc_kind="paper")


def test_handout_still_reports_span_overlap():
    """讲义关掉的是单题级规则，区间重叠这种契约违约仍然要报。"""
    lines = _lines(["【例1】题干", "解析", "【例2】下一题"])
    records = [_record(0, lines[0].y0, lines[1].y0), _record(0, lines[1].y0, lines[2].y0)]
    spans = [_span(1, "【例1】", 1, 2), _span(2, "【例2】", 2, 3)]
    findings = boundary_audit(lines, records, spans, doc_kind="handout")
    assert [f.kind for f in findings] == ["span_overlap"]
