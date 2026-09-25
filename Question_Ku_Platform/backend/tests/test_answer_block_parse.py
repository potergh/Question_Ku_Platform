"""答案块短答切分：不能吞下一行的【分析】，也不能只取一行。

实测和平卷答案区（2022 天津和平一模）：
- 第 20 题答案是图，原文是「【答案】」换行后直接跟「【分析】…」。旧正则
  r"【\\s*答案\\s*】\\s*([^\\n]*)" 里的 \\s* 会跨过换行，把【分析】整行当成答案，
  结果 answer 字段存进了「【分析】先根据欧姆定律求出不同接线柱间电阻的大小…」。
- 第 21 题答案分两个小问、【答案】后同段两行：旧正则的 [^\\n]* 只取第一行，
  「（2）额定电压下，加热棒每次工作的时间是 58.3min。」直接丢失。
"""

from __future__ import annotations

import pytest

from physics_paper_splitter.answers import parse_answer_block


def test_answer_marker_empty_does_not_swallow_analysis():
    """【答案】后没内容时答案留空，绝不能把下一行【分析】当答案。"""
    lines = [
        "如图，盒内有一个电压为9V 的电源。（题干重印）",
        "【答案】",
        "【分析】先根据欧姆定律求出不同接线柱间电阻的大小，然后确定电源的位置",
        "【解答】解：盒内电路分别跟盒外A、B、C、D 四个接线端中的三个接线端相连",
    ]
    parsed = parse_answer_block(20, 28, lines)
    assert parsed["answer"] is None


def test_answer_marker_keeps_all_subquestion_lines():
    """【答案】后跨多行的小问答案要全部保留。"""
    lines = [
        "【答案】（1）正常工作时，水吸收的热量是8.4×105J；",
        "（2）额定电压下，加热棒每次工作的时间是58.3min。",
        "【分析】（1）根据Q 吸＝c 水m（t﹣t0）求水吸收的热量；",
    ]
    parsed = parse_answer_block(21, 29, lines)
    assert parsed["answer"] == (
        "（1）正常工作时，水吸收的热量是8.4×105J；\n"
        "（2）额定电压下，加热棒每次工作的时间是58.3min。"
    )


def test_answer_marker_value_on_same_line():
    """选择题答案仍按同行取值。"""
    parsed = parse_answer_block(1, 12, ["【答案】D", "【分析】声音是由物体振动产生的。"])
    assert parsed["answer"] == "D"


def test_choice_conclusion_still_used_without_marker():
    """没有【答案】标记时，仍从「故选：X」取答案。"""
    parsed = parse_answer_block(3, 13, ["【解答】解：…经验证只有该项符合，故选：B。"])
    assert parsed["answer"] == "B"


def test_pointer_answer_is_not_treated_as_the_answer():
    """「见试题解答内容」是指路牌，不是答案（实测和平卷第 16 题）。

    留着它的危害：answer_key_llm 那一路漏了这道题时，它会以「答案」的身份补位，
    产物里看起来有答案、实际是一句空话。置空后该题走 needs_review，一眼看得出要补。
    """
    lines = [
        "【答案】见试题解答内容",
        "【分析】液体和气体都称为流体，流体的流速越大，压强越小。",
        "【解答】解：喷射空气因流速大，压强小，周围空气向这部分喷射空气靠近。",
    ]
    parsed = parse_answer_block(16, 24, lines)

    assert parsed["answer"] is None
    assert parsed["analysis"], "解析正文必须完整保留，指路牌丢掉不影响它"


@pytest.mark.parametrize(
    "pointer",
    ["见解析", "答案见解析", "详见解答", "（见试题解答内容）", "见详解"],
)
def test_pointer_variants_are_all_rejected(pointer):
    parsed = parse_answer_block(16, 24, [f"【答案】{pointer}", "【分析】略。"])

    assert parsed["answer"] is None


@pytest.mark.parametrize(
    "real_answer",
    ["C", "小；靠近", "1.5A；1A", "见上图", "如图", "因为电流表被短路，所以L₁不亮"],
)
def test_real_answers_are_kept(real_answer):
    """守卫别扩太大：真答案里可能带「见」或「如图」，那不是指路牌。"""
    parsed = parse_answer_block(8, 20, [f"【答案】{real_answer}", "【分析】略。"])

    assert parsed["answer"] == real_answer


def test_content_after_answer_before_analysis_is_kept():
    """【答案】与【分析】之间的内容（含换行续行）都算答案。"""
    lines = [
        "【答案】104；1：4。",
        "（续行内容）",
        "【点评】本题考查了密度公式的应用。",
    ]
    parsed = parse_answer_block(19, 27, lines)
    assert parsed["answer"] == "104；1：4。\n（续行内容）"
