"""选项标签解析的回归测试。

实测来源（和平卷 Q7/Q8）：这两题的选项**内容是图**，排版成

    A．  [图]        B．  [图]
    C．  [图]        D．  [图]

旧正则 `(?:^|\\s)([A-D])…` 的前导是**消耗性**匹配，加上末尾 `\\s*` 也吃空白，
同行第二个标签因此「前面没有空白」而失配 → 解析成 `{'A': 'B．', 'C': 'D．'}`：
4 个选项压成 2 个、内容还串到相邻标签上。改用零宽断言 `(?<!\\S)` 后恢复正常。
"""

from __future__ import annotations

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from physics_paper_splitter.ocr.structure import parse_content  # noqa: E402


def test_inline_labels_with_image_options_keep_all_four():
    """同行相邻标签（选项为图，标签间只有空白）必须解析出 4 个选项。"""
    body = ("7．（3 分）在一个电路中，需要通过声纹与人脸识别成功后才能开门（  ）\n"
            "A．                    B．\n"
            "C．                    D．")

    out = parse_content(body)

    assert list(out["options"]) == ["A", "B", "C", "D"], "同行第二个标签不能被吞掉"
    assert all(out["options"][k] is None for k in "ABCD"), "选项内容是图 → 无文字"


def test_text_options_are_not_shifted():
    """常规逐行文本选项：标签与内容不得错位。"""
    body = "1．（3 分）下列说法正确的是（  ）\nA．甲\nB．乙\nC．丙\nD．丁"

    out = parse_content(body)

    assert out["options"] == {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    assert out["stem"] == "下列说法正确的是（  ）"
    assert out["score"] == 3


def test_two_options_per_line_with_text():
    """一行两个选项且带内容：取值不得跨到下一个标签。"""
    body = "2．（3 分）题干（  ）\nA．甲　　B．乙\nC．丙　　D．丁"

    out = parse_content(body)

    assert out["options"] == {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}


def test_question_without_options_is_untouched():
    """无选项的题（填空/解答）不应被误切出选项。"""
    body = "14．（4 分）如图所示，此时天平的读数为      g。"

    out = parse_content(body)

    assert out["options"] == {}
    assert out["stem"].startswith("如图所示")
