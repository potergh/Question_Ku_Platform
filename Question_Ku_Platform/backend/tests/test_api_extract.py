"""api_extract 边界判定 / 分批归并 / 逐题结构化的回归测试。

全部 mock 掉网络出口（call_vlm_json），不发任何真实请求：
- 几何用空白 fitz 页（真实 rect，_content_bottom 退化为页高 - 82）；
- 行清单手工构造，line_id 单调递增，与 build_line_inventory 的产出同构。
"""

from __future__ import annotations

import pymupdf as fitz
import pytest

# 先 import api_extract（在包 __init__ 里把 packages/ 注入 sys.path），
# 之后 physics_paper_splitter 才可被导入。
from app.services.api_extract import ExtractCancelled
from app.services.api_extract import boundary as boundary_mod
from app.services.api_extract import structure as structure_mod
from app.services.api_extract.boundary import (
    BoundaryResult,
    QuestionSpan,
    _doc_kind,
    _merge_reports,
    _owned_ranges,
    _parse_questions,
    _parse_regions,
    detect_boundaries,
    plan_batches,
)
from app.services.api_extract.structure import structure_questions
from app.services.api_extract.vlm_client import VLMError
from physics_paper_splitter.lines import TextLine

# 空白页几何：595×842（A4），正文下边界 = 842 - 82 = 760。
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
FIRST_Y0 = 60.0
LINE_GAP = 30.0
LINE_HEIGHT = 14.0


def _doc(page_count: int) -> fitz.Document:
    """空白 PDF：几何真实，且没有文字层可供 extract_line_inventory 使用。"""
    doc = fitz.open()
    for _ in range(page_count):
        doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    return doc


def _page_lines(spec: dict[int, list[str]]) -> list[TextLine]:
    """按 {页索引: [行文本]} 造出行清单，line_id 从 1 起按页序递增。"""
    lines: list[TextLine] = []
    line_id = 0
    for page in sorted(spec):
        for index, text in enumerate(spec[page]):
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
                    text=text,
                )
            )
    return lines


def _question(start: int, end: int, label: str = "1") -> dict:
    return {
        "label": label,
        "section": None,
        "qtype": None,
        "score": None,
        "start_line": start,
        "end_line": end,
    }


def _fake_vlm(monkeypatch, payload, *, module=boundary_mod, calls: list | None = None):
    """把某个模块里的 call_vlm_json 换成固定/可调用 payload。

    payload 可以是 dict，也可以是 (user_text) -> dict|Exception 的函数，
    后者用来模拟部分题目失败。
    """

    async def fake(config, *, system, user_text, image_paths=None, **kwargs):
        if calls is not None:
            calls.append(user_text)
        value = payload(user_text) if callable(payload) else payload
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(module, "call_vlm_json", fake)
    return fake


# ── 行清单 -> QuestionRecord ─────────────────────────────────────────


async def test_paper_inventory_to_records(monkeypatch):
    doc = _doc(2)
    lines = _page_lines(
        {0: ["1．第一题题干", "选项 A 内容", "选项 B 内容"], 1: ["2．第二题题干", "填空一", "填空二"]}
    )
    payload = {
        "doc_kind": "paper",
        "questions": [
            {"label": "1", "type": "single_choice", "score": 3, "start_line": 1, "end_line": 3},
            {"label": "2", "type": "fill_blank", "score": 4, "start_line": 4, "end_line": 6},
        ],
        "non_question_regions": [],
    }
    _fake_vlm(monkeypatch, payload)

    result = await detect_boundaries({"model": "x"}, doc, lines)

    assert result.doc_kind == "paper"
    assert len(result.records) == 2
    first, second = result.records
    assert first.filename == "Q001.webp"
    assert first.label == "1"
    assert first.start_page == 1
    assert first.end_page == 1
    assert first.segments  # 非空：切片几何算得出
    assert second.start_page == 2
    # spans 与 records 按下标一一对应，qtype/score 透传自边界判定
    assert [span.qtype for span in result.spans] == ["single_choice", "fill_blank"]
    assert [span.score for span in result.spans] == [3.0, 4.0]
    doc.close()


async def test_handout_two_numbering_schemes_to_records(monkeypatch):
    """讲义用两套编号（【例1】/随堂检测 1），label 必须原样保留、不合并。"""
    doc = _doc(1)
    lines = _page_lines({0: ["【例1】讲解正文", "随堂检测 1．练习正文"]})
    payload = {
        "doc_kind": "handout",
        "questions": [
            {"label": "【例1】", "start_line": 1, "end_line": 1},
            {"label": "随堂检测 1", "start_line": 2, "end_line": 2},
        ],
        "non_question_regions": [],
    }
    _fake_vlm(monkeypatch, payload)

    result = await detect_boundaries({"model": "x"}, doc, lines)

    assert result.doc_kind == "handout"
    assert [record.label for record in result.records] == ["【例1】", "随堂检测 1"]
    doc.close()


async def test_cross_page_question_yields_multi_segment_records(monkeypatch):
    doc = _doc(2)
    lines = _page_lines({0: ["卷首信息", "1．跨页题目开始"], 1: ["题目续行", "题目结束"]})
    payload = {
        "doc_kind": "paper",
        "questions": [{"label": "1", "start_line": 2, "end_line": 3}],
        "non_question_regions": [{"start_line": 1, "end_line": 1, "kind": "cover"}],
    }
    _fake_vlm(monkeypatch, payload)

    result = await detect_boundaries({"model": "x"}, doc, lines)

    assert len(result.records) == 1
    record = result.records[0]
    assert record.is_cross_page is True
    assert record.start_page == 1
    assert record.end_page == 2
    assert len(record.segments) == 2
    assert [segment.page_index for segment in record.segments] == [0, 1]
    # 非题目区域进 excluded，不计入覆盖率分母
    assert result.excluded_line_ids == {1}
    doc.close()


# ── 分批与归属 ───────────────────────────────────────────────────────


def test_plan_batches_overlaps_last_page():
    """12 页、每页 1 行：字符预算不触发，改由 MAX_BATCH_PAGES=10 切两批，批间重叠 1 页。"""
    lines = _page_lines({page: [f"第{page}页文字"] for page in range(12)})
    assert plan_batches(lines) == [(0, 9), (9, 11)]


def test_owned_ranges_split_lines_without_loss():
    """按 line_id 半开区间划分归属：每一行恰好属于一个批次，无重叠无遗漏。"""
    lines = _page_lines({page: [f"第{page}页文字"] for page in range(12)})
    batches = plan_batches(lines)
    assert _owned_ranges(batches, lines) == [(0, 10), (10, 12)]


# ── 跨批归并 ─────────────────────────────────────────────────────────


def test_merge_reports_dedupes_overlap_and_keeps_longest_tail():
    """同一 start_line 被两批都报出时只留一条，end_line 取最长（跨批长题不被截断）。"""
    reports = [
        ((0, 10), [_question(10, 10)], []),
        ((10, 12), [_question(10, 12)], []),
    ]
    warnings: list[str] = []
    questions, regions = _merge_reports(reports, 12, warnings)

    assert regions == []
    assert len(questions) == 1
    assert questions[0]["start_line"] == 10
    assert questions[0]["end_line"] == 12


def test_merge_reports_truncates_and_honours_question_priority():
    """同批内区间重叠时截断前一条；非题目区域与题目重叠时被整条忽略。"""
    reports = [
        (
            (0, 20),
            [_question(1, 5), _question(4, 8, label="2")],
            [{"start_line": 5, "end_line": 7, "kind": "instruction"}],
        )
    ]
    warnings: list[str] = []
    questions, regions = _merge_reports(reports, 20, warnings)

    assert [(row["start_line"], row["end_line"]) for row in questions] == [(1, 3), (4, 8)]
    assert regions == []
    assert any("前一条被截断" in item for item in warnings)
    assert any("与题目区间重叠" in item for item in warnings)


# ── LLM 响应解析 ─────────────────────────────────────────────────────


def test_parse_questions_rejects_out_of_range_and_fixes_inverted():
    line_index = {line.line_id: line for line in _page_lines({0: ["a", "b", "c", "d", "e"]})}
    payload = {
        "questions": [
            {"label": "1", "type": "single_choice", "score": 3, "start_line": 1, "end_line": 2},
            {"label": "2", "start_line": 1, "end_line": 99},
            {"label": "3", "start_line": 5, "end_line": 3},
        ]
    }
    valid, dropped = _parse_questions(payload, line_index)

    # 第 2 条越界被丢弃；第 3 条区间倒置被自动纠正后保留（不是丢弃）
    assert valid == [
        {
            "label": "1",
            "section": None,
            "qtype": "single_choice",
            "score": 3.0,
            "start_line": 1,
            "end_line": 2,
        },
        {
            "label": "3",
            "section": None,
            "qtype": None,
            "score": None,
            "start_line": 3,
            "end_line": 5,
        },
    ]
    assert any("越界" in item for item in dropped)
    assert any("倒置" in item for item in dropped)


def test_parse_questions_missing_array_reports_reason():
    valid, dropped = _parse_questions({}, {})
    assert valid == []
    assert dropped == ["响应缺少 questions 数组"]


def test_parse_regions_unknown_kind_becomes_other():
    line_index = {line.line_id: line for line in _page_lines({0: ["a", "b", "c", "d"]})}
    payload = {
        "non_question_regions": [
            {"start_line": 1, "end_line": 2, "kind": "cover"},
            {"start_line": 3, "end_line": 4, "kind": "weird"},
            {"start_line": 9, "end_line": 9, "kind": "cover"},
        ]
    }
    regions = _parse_regions(payload, line_index)

    assert [row["kind"] for row in regions] == ["cover", "other"]


def test_doc_kind_override_and_majority():
    assert _doc_kind([], "handout") == "handout"
    # handout 过半才判讲义，否则沿用首个批次的判定
    assert _doc_kind(["handout", "handout", "paper"], None) == "handout"
    assert _doc_kind(["paper", "paper", "handout"], None) == "paper"
    assert _doc_kind([], None) == "paper"


# ── 逐题结构化：容错与取消 ───────────────────────────────────────────


async def test_structure_single_failure_does_not_break_batch(monkeypatch):
    lines = _page_lines({0: ["1．正常题目", "正常题干第二行", "2．坏题", "坏题第二行"]})
    boundary = BoundaryResult(
        spans=[
            QuestionSpan(
                qid=1, label="1", section=None, qtype="single_choice", score=3.0,
                start_line=1, end_line=2,
            ),
            QuestionSpan(
                qid=2, label="2", section=None, qtype=None, score=None,
                start_line=3, end_line=4,
            ),
        ]
    )

    async def fake(config, *, system, user_text, image_paths=None, **kwargs):
        if "坏题" in user_text:
            raise VLMError("模拟失败")
        return {
            "stem_md": "正常题干",
            "options": [{"label": "A", "content": "甲"}],
            "type": "single_choice",
            "score": 3,
        }

    monkeypatch.setattr(structure_mod, "call_vlm_json", fake)
    items = await structure_questions({"model": "x"}, lines, boundary, {}, {})

    assert len(items) == 2
    ok, bad = items
    assert ok.qid == 1
    assert ok.error is None
    assert ok.needs_review is False
    assert ok.stem_md == "正常题干"
    assert ok.options == [{"label": "A", "content": "甲"}]
    # 失败那一题留错误说明，但不影响同批其它题
    assert bad.qid == 2
    assert bad.error is not None and "模拟失败" in bad.error
    assert bad.needs_review is True


async def test_structure_cancellation_propagates(monkeypatch):
    lines = _page_lines({0: ["1．题目正文"]})
    boundary = BoundaryResult(
        spans=[
            QuestionSpan(
                qid=1, label="1", section=None, qtype=None, score=None,
                start_line=1, end_line=1,
            )
        ]
    )

    async def cancel_check():
        return True

    async def fake(config, **kwargs):
        raise AssertionError("取消后不应再发起模型请求")

    monkeypatch.setattr(structure_mod, "call_vlm_json", fake)
    with pytest.raises(ExtractCancelled):
        await structure_questions(
            {"model": "x"}, lines, boundary, {}, {}, cancel_check=cancel_check
        )


# ── 边界判定：取消 / 异常响应 / 空清单 ───────────────────────────────


async def test_boundary_cancellation_before_any_request(monkeypatch):
    doc = _doc(1)
    lines = _page_lines({0: ["1．题目正文"]})
    calls: list[str] = []
    _fake_vlm(
        monkeypatch,
        {"doc_kind": "paper", "questions": [], "non_question_regions": []},
        calls=calls,
    )

    async def cancel_check():
        return True

    with pytest.raises(ExtractCancelled):
        await detect_boundaries({"model": "x"}, doc, lines, cancel_check=cancel_check)
    assert calls == []
    doc.close()


async def test_boundary_non_object_payload_raises(monkeypatch):
    doc = _doc(1)
    lines = _page_lines({0: ["1．题目正文"]})
    _fake_vlm(monkeypatch, ["这不是对象"])

    with pytest.raises(VLMError) as excinfo:
        await detect_boundaries({"model": "x"}, doc, lines)
    assert "返回非对象" in str(excinfo.value)
    doc.close()


async def test_boundary_empty_inventory_warns_without_network(monkeypatch):
    doc = _doc(1)
    calls: list[str] = []
    _fake_vlm(
        monkeypatch,
        {"doc_kind": "paper", "questions": [], "non_question_regions": []},
        calls=calls,
    )

    result = await detect_boundaries({"model": "x"}, doc, [])

    assert result.records == []
    assert result.spans == []
    assert result.warnings and "行清单为空" in result.warnings[0]
    assert calls == []
    doc.close()


# ── 小问泄漏修复 ─────────────────────────────────────────────────────


def _subq_line(line_id: int, text: str) -> TextLine:
    return TextLine(
        line_id=line_id, page_index=0,
        y0=60.0 + line_id * 30.0, y1=74.0 + line_id * 30.0,
        x0=0.0, x1=595.0, text=text,
    )


def test_repair_subquestion_leak_moves_lines_back():
    """上一题的小问被划进本题区间：确定性还回去，而不是只标 needs_review。

    实测 MinerU 和平卷：第 21 题的（2）被划进第 22 题区间，第 22 题题干开头
    是上一题的半截小问、题卡图里也有。boundary_audit 只能标 needs_review，
    **内容还是错的**，用户得手动删 —— 所以要在构建裁卡片段之前修掉。
    """
    lines = {
        0: _subq_line(0, "21．（6 分）用一只加热棒给鱼缸内的水加热。"),
        1: _subq_line(1, "(1) 正常工作时，水吸收的热量是多少？"),
        2: _subq_line(2, "(2) 额定电压下，加热棒每次工作的时间是多少分钟？"),
        3: _subq_line(3, "22．如图所示电路中，小灯泡 L 标有“6V 6W”字样。"),
        4: _subq_line(4, "求：（1）电源电压；（2）电阻 R1 的阻值。"),
    }
    questions = [
        {"label": "21.", "start_line": 0, "end_line": 1},
        {"label": "22.", "start_line": 2, "end_line": 4},   # ← 开头混入了 21 的 (2)
    ]
    warnings: list[str] = []

    repaired = boundary_mod.repair_subquestion_leak(lines, questions, warnings)

    assert repaired == 1
    assert questions[0]["end_line"] == 2       # (2) 那行还给了 21
    assert questions[1]["start_line"] == 3     # 22 从自己的题号行开始
    assert any("还给第 21 题" in w for w in warnings)


def test_repair_subquestion_leak_requires_prev_first_sub():
    """上一题区间里没有 (1) 时不动：这些行可能真是本题自己的小问序列。"""
    lines = {
        0: _subq_line(0, "21．某题干没有小问。"),
        1: _subq_line(1, "(2) 另起一段，但它长得像小问。"),
        2: _subq_line(2, "22．真正的下一题。"),
    }
    questions = [
        {"label": "21.", "start_line": 0, "end_line": 0},
        {"label": "22.", "start_line": 1, "end_line": 2},
    ]

    assert boundary_mod.repair_subquestion_leak(lines, questions, []) == 0
    assert questions[1]["start_line"] == 1     # 原样不动


def test_repair_subquestion_leak_skips_first_subquestion():
    """首行是 (1) 时不动 —— 它可能真是本题的第一小问，动了会拆走题头。"""
    lines = {
        0: _subq_line(0, "21．上一题。"),
        1: _subq_line(1, "(1) 本题第一小问。"),
        2: _subq_line(2, "22．真正的下一题。"),
    }
    questions = [
        {"label": "21.", "start_line": 0, "end_line": 0},
        {"label": "22.", "start_line": 1, "end_line": 2},
    ]

    assert boundary_mod.repair_subquestion_leak(lines, questions, []) == 0


def test_repair_subquestion_leak_needs_own_main_number():
    """本题区间里找不到自己的主编号行时不动 —— 修了本题就没题头了。"""
    lines = {
        0: _subq_line(0, "21．上一题。"),
        1: _subq_line(1, "(1) 上一题的第一小问。"),
        2: _subq_line(2, "(2) 上一题的第二小问。"),
    }
    questions = [
        {"label": "21.", "start_line": 0, "end_line": 0},
        {"label": "22.", "start_line": 1, "end_line": 2},
    ]

    assert boundary_mod.repair_subquestion_leak(lines, questions, []) == 0


# ── 单批响应形状的容错 ───────────────────────────────────────────────


async def test_bare_questions_array_is_repaired(monkeypatch):
    """模型把 questions 数组直接吐出来（外面不包对象）时不能让整份文档报废。

    真实样本踩到过：38 页混合卷在「第 19-28 页」批次返回裸数组，整份归零。
    """
    _fake_vlm(
        monkeypatch,
        [{"label": "1", "type": "single_choice", "score": 3, "start_line": 1, "end_line": 3}],
    )
    doc = _doc(1)
    lines = _page_lines({0: ["1．第一题题干", "选项 A", "选项 B"]})

    result = await detect_boundaries({"model": "x"}, doc, lines)

    assert len(result.spans) == 1
    assert any("裸数组" in warning for warning in result.warnings)
    doc.close()


async def test_non_object_payload_is_retried_before_failing(monkeypatch):
    """单个批次抖动不能直接抛穿：重试耗尽才失败，否则整份文档的调用全白烧。"""
    calls: list[str] = []
    _fake_vlm(monkeypatch, "oops", calls=calls)
    doc = _doc(1)
    lines = _page_lines({0: ["1．第一题题干"]})

    with pytest.raises(VLMError):
        await detect_boundaries({"model": "x"}, doc, lines)

    assert len(calls) == 3  # 首次 + 2 次重试
    doc.close()


async def test_garbage_array_is_not_treated_as_questions(monkeypatch):
    """数组容错要有限度：不像题目的数组照样报错，不然更难查。"""
    _fake_vlm(monkeypatch, ["这不是对象"])
    doc = _doc(1)
    lines = _page_lines({0: ["1．第一题题干"]})

    with pytest.raises(VLMError):
        await detect_boundaries({"model": "x"}, doc, lines)
    doc.close()


# ── 卡图片段边界 ────────────────────────────────────────────────────


def _build_records_for(spec: dict[int, list[str]], questions: list[dict]):
    doc = _doc(max(spec) + 1)
    lines = _page_lines(spec)
    line_index = {line.line_id: line for line in lines}
    lines_by_page: dict[int, list] = {}
    for line in lines:
        lines_by_page.setdefault(line.page_index, []).append(line)
    records = boundary_mod._build_records(doc, line_index, lines_by_page, questions, [])
    doc.close()
    return records


def test_card_segment_starts_at_the_question_not_the_page_top():
    """同页靠后的题不能从页顶起裁。

    早前上边界写成 min(top_margin, 首行上方留白)，只要题目不在页顶就一律
    落到 top_margin，把同页前面几道题整段裁进本题卡图 —— 实测和平卷第 16 题
    卡图高 725pt，等于整页内容高度。
    """
    spec = {0: ["1．第一题", "选项A", "选项B", "2．第二题", "选项C", "选项D"]}
    questions = [_question(1, 3, "1．"), _question(4, 6, "2．")]

    records = _build_records_for(spec, questions)

    assert len(records) == 2
    # 首行 y0 = 60，上边界 = 60 - 4 = 56。
    assert records[0].segments[0].y0 == pytest.approx(56.0, abs=0.5)
    # 第 2 题首行 y0 = 60 + 30*3 = 150，上边界 = 146，而不是页边距 44。
    assert records[1].segments[0].y0 == pytest.approx(146.0, abs=0.5)


def test_card_segment_clamps_to_top_margin():
    """题目首行贴近页顶时用页边距兜底，不能越过正文上边距裁进页眉。"""
    lines = _page_lines({0: ["1．第一题"]})
    lines[0].y0 = 46.0
    line_index = {line.line_id: line for line in lines}
    doc = _doc(1)

    records = boundary_mod._build_records(doc, line_index, {0: lines}, [_question(1, 1)], [])

    assert records[0].segments[0].y0 == pytest.approx(44.0, abs=0.5)
    doc.close()


def test_cross_page_segment_starts_at_page_top():
    """跨页续段从页顶起裁：内容自上一页延续，页面顶部仍属于本题。"""
    spec = {0: ["1．第一题", "选项A"], 1: ["2．第二题", "选项B", "选项C", "1．续"]}
    questions = [_question(1, 4, "1．"), _question(5, 6, "2．")]

    records = _build_records_for(spec, questions)

    tail = [seg for seg in records[0].segments if seg.page_index == 1]
    assert tail, "跨页题应有第 2 页片段"
    assert tail[0].y0 == pytest.approx(44.0, abs=0.5)


# ── 尾部插图（题干排到页底，图被挤到下一页） ─────────────────────────


def _line(line_id: int, page_index: int, y0: float, text: str = "文本"):
    return TextLine(
        line_id=line_id,
        page_index=page_index,
        y0=y0,
        y1=y0 + LINE_HEIGHT,
        x0=40.0,
        x1=520.0,
        text=text,
    )


def _image_stream() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    image = Image.new("RGB", (240, 160), "white")
    image.paste((0, 0, 0), (12, 12, 228, 148))
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _doc_with_figures(page_count: int, figures: dict[int, list[tuple]]):
    """空白页 + 指定位置插入位图，用于验证插图相关几何。"""
    stream = _image_stream()
    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        for rect in figures.get(index, []):
            page.insert_image(fitz.Rect(rect), stream=stream)
    return doc


def _records_from(doc, lines, questions, *, question_page_count=None):
    line_index = {line.line_id: line for line in lines}
    lines_by_page: dict[int, list] = {}
    for line in lines:
        lines_by_page.setdefault(line.page_index, []).append(line)
    return boundary_mod._build_records(
        doc,
        line_index,
        lines_by_page,
        questions,
        [],
        question_page_count=question_page_count,
    )


def test_trailing_figure_on_next_page_joins_the_card():
    """题干排到页底、插图被挤到下一页顶部时，图必须并进本题卡图。

    实测和平卷第 16 题（「如图」）：文字止于第 6 页底部，图在第 7 页顶部
    y=76~178，下一题首行在 y=182。原实现只裁 start..end 页，这张图既不在卡图
    里也不归属任何题目，直接丢失。
    """
    lines = [_line(1, 0, 60.0), _line(2, 0, 90.0), _line(3, 1, 200.0), _line(4, 1, 230.0)]
    questions = [_question(1, 2, "1．"), _question(3, 4, "2．")]
    doc = _doc_with_figures(2, {1: [(104.0, 60.0, 240.0, 160.0)]})

    records = _records_from(doc, lines, questions, question_page_count=2)

    first = records[0]
    assert [seg.page_index for seg in first.segments] == [0, 1]
    tail = first.segments[1]
    # 从页顶起裁，止于插图底部 + 4pt（PyMuPDF 会按比例微调插入矩形，取实际值）。
    actual = doc[1].get_image_rects(doc[1].get_images(full=True)[0][0])[0]
    assert tail.y0 == pytest.approx(44.0, abs=0.5)
    assert tail.y1 == pytest.approx(actual.y1 + 4.0, abs=0.5)
    # 卡片实际铺到第 2 页，元数据要跟上。
    assert first.end_page == 2
    assert first.is_cross_page is True
    # 下一题的首行不能被卷进来。
    assert records[1].segments[0].y0 == pytest.approx(196.0, abs=0.5)
    doc.close()


def test_tail_scan_stops_at_last_question_page():
    """尾部扫描不能越过题目页 —— 否则最后一题会把整段答案/解析页扫进卡图。"""
    lines = [_line(1, 0, 60.0), _line(2, 0, 90.0)]
    questions = [_question(1, 2, "1．")]
    doc = _doc_with_figures(4, {2: [(104.0, 60.0, 240.0, 160.0)]})

    records = _records_from(doc, lines, questions, question_page_count=2)

    assert [seg.page_index for seg in records[0].segments] == [0]
    assert records[0].end_page == 1
    doc.close()


def test_no_tail_segment_when_gap_has_no_figure():
    """间隙里没有插图就不补段，避免凭空多出一张空白卡页。"""
    lines = [_line(1, 0, 60.0), _line(2, 1, 200.0)]
    questions = [_question(1, 1, "1．"), _question(2, 2, "2．")]
    doc = _doc_with_figures(2, {})

    records = _records_from(doc, lines, questions, question_page_count=2)

    assert [seg.page_index for seg in records[0].segments] == [0]
    doc.close()


# ── 固定下边距不能切掉本题末行 ───────────────────────────────────────


def _doc_custom(height: float, page_count: int = 1) -> fitz.Document:
    doc = fitz.open()
    for _ in range(page_count):
        doc.new_page(width=PAGE_WIDTH, height=height)
    return doc


def test_segment_bottom_covers_question_last_line():
    """_content_bottom 对扫描件退化成「页高 - 82」，不能拿它切掉本题末行。

    实测河东卷页高 792pt（不是 A4 的 842），content_bottom 算成 710，而每页
    真实末行在 743~792 —— 全卷每页尾部 33~82pt 被切掉（选项 A/B/C/D 就在那）。
    """
    doc = _doc_custom(792.0)
    lines = [_line(1, 0, 600.0), _line(2, 0, 760.0)]
    questions = [_question(1, 2, "1．")]

    records = _records_from(doc, lines, questions, question_page_count=1)

    seg = records[0].segments[0]
    assert seg.y0 == pytest.approx(596.0, abs=0.5)
    # content_bottom = 710，但末行底部 774 必须收进来（+4pt 留白）。
    assert seg.y1 == pytest.approx(778.0, abs=0.5)
    doc.close()


def test_question_below_content_bottom_still_gets_a_segment():
    """整题都落在固定边距之下时，原实现 y1 < y0 直接丢段 —— 卡图整个缺失。

    实测河东卷第 7 题正是这种情况：题干与四个选项全在 y=764~792。
    """
    doc = _doc_custom(792.0)
    lines = [_line(1, 0, 750.0), _line(2, 0, 770.0)]
    questions = [_question(1, 2, "1．")]

    records = _records_from(doc, lines, questions, question_page_count=1)

    assert len(records[0].segments) == 1
    seg = records[0].segments[0]
    assert seg.y0 == pytest.approx(746.0, abs=0.5)
    assert seg.y1 == pytest.approx(788.0, abs=0.5)
    doc.close()


def test_extension_is_capped_at_page_height():
    """末行贴着页底时不能算出超过页高的裁切矩形。"""
    doc = _doc_custom(792.0)
    lines = [_line(1, 0, 700.0), _line(2, 0, 791.0)]
    questions = [_question(1, 2, "1．")]

    records = _records_from(doc, lines, questions, question_page_count=1)

    assert records[0].segments[0].y1 == pytest.approx(792.0, abs=0.5)
    doc.close()
