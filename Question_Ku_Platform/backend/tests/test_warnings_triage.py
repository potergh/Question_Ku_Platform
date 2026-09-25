"""识别警告分级：用户级与管线诊断的判据。

分级只影响展示，不参与审计闸门；这里锁的是「哪些文案该出现在用户面前」。
"""

from app.utils.warnings import is_diagnostic, split_warnings


def test_internal_coordinates_are_diagnostic():
    assert is_diagnostic("非题目区域 line 602..613 (answer_key) 与题目区间重叠，已忽略该区域")
    assert is_diagnostic("题号锚点校正：第 21 题起点从 line 136 前移到 line 135")
    assert is_diagnostic("有 520 行未被任何区间覆盖：#99, #200, #201")
    assert is_diagnostic("非题目区与题目区间重叠，前一条被截断到 line 399")
    assert is_diagnostic("已忽略 1 类跨页复现的装饰图（页码/水印/logo）")


def test_user_actionable_warnings_stay_visible():
    assert not is_diagnostic("第 [21, 23] 页没有可用文字层，改走视觉模型整页转写。")
    assert not is_diagnostic("答案/解析区（第 10 页起）里的 23 道题是正文重印，已剔除。")
    assert not is_diagnostic("有 3 道题在答案区只找到编号、没有可抄写的答案，已标为待复核")


def test_broken_glyph_warning_stays_user_visible():
    """「有文字层、只是公式字形取不回」与「扫描件」是两件事，都该给老师看到。

    实测被误报的页数（和平 13、南开 11、红桥 8）—— 这些页的有效字符在 531~893
    之间，却被旧文案说成「没有可用文字层」。新文案必须仍是用户级，
    否则分级一改就等于把这个信息重新藏起来。
    """
    assert not is_diagnostic(
        "第 [14, 19, 21] 页有文字层，但含无法从字体取回的字符（多为公式），"
        "改走视觉模型整页转写。"
    )


def test_split_partitions_everything_and_keeps_order():
    raw = [
        "第 [1] 页没有可用文字层，改走视觉模型整页转写。",
        "非题目区域 line 22..31 (section_header) 与题目区间重叠，已忽略该区域",
        "已忽略 1 类跨页复现的装饰图（页码/水印/logo）",
        "答案区有 15 个题号没能与题目自动配对，已跳过「按题号配对」这一路答案来源",
    ]
    user, diagnostic = split_warnings(raw)
    assert user == [raw[0], raw[3]]
    assert diagnostic == [raw[1], raw[2]]
    # 一条都不能丢：分级是展示问题，不是过滤。
    assert len(user) + len(diagnostic) == len(raw)


def test_empty_input():
    assert split_warnings(None) == ([], [])
    assert split_warnings([]) == ([], [])
