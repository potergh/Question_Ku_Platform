"""表格当插图（「表格只有一半」的修复）单元测试。

背景：2026 河东一模第 24 题是一张 7 行 16 格、含 colspan/rowspan 的表格，模型按
structure prompt 把它转成 Markdown 后合并关系全丢 —— `<td rowspan="3">方案一</td>`
变成 `| 方案一 |  |`，方案一/方案二的分组消失，界面上就只剩"一半表格"。
Markdown 语法里根本没有合并单元格，所以修法不是让模型抄得更好，而是改用 MinerU
按版面渲染的整张表格图（实测合并关系、空格线都在）。

这里锁住四件事：
  1. 表格 / 图表块确实会变成插图候选（含诊断计数）；
  2. 表格块没拿到渲染图时不静默（告警）—— 否则用户只会看到表格缺内容；
  3. prompt 的表格规则按通道分岔，且模板里的 JSON 花括号不被 format 弄坏；
  4. 只有**每个**表格都有图时才禁止模型重抄（否则内容整块丢失）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.api_extract.prompts import (
    TABLE_CLAUSE_FIGURE,
    TABLE_CLAUSE_MARKDOWN,
    structure_system_prompt,
)
from app.services.mineru_adapter import build_figure_candidates
from app.services.api_extract.structure import (
    _mask_table_html,
    _tables_covered,
    strip_markdown_tables,
)
from physics_paper_splitter.lines import TextLine

PAGE_SIZES = {0: (595.0, 842.0)}


def _content_list(tmp_path: Path, blocks: list[dict]) -> Path:
    path = tmp_path / "x_content_list.json"
    path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    return path


def _write_image(tmp_path: Path, name: str = "images/t.jpg") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"jpg")
    return path


# ── 块类型 ───────────────────────────────────────────────────────────


def test_table_block_becomes_candidate(tmp_path):
    """表格块要变成插图候选 —— 这是「表格只有一半」的正解。

    原来 build_figure_candidates 只认 type == "image"，表格块进不来；而它的
    table_body 是 HTML，模型按 prompt 转 Markdown 必然丢合并单元格。
    """
    image = _write_image(tmp_path)
    path = _content_list(tmp_path, [
        {"type": "text", "text": "24．测量小瓷杯的密度", "bbox": [100, 100, 900, 130],
         "page_idx": 0},
        {"type": "table", "table_body": '<table><tr><td colspan="2">x</td></tr></table>',
         "img_path": "images/t.jpg", "bbox": [100, 200, 900, 500], "page_idx": 0},
    ])
    inventory = build_figure_candidates(path, page_sizes=PAGE_SIZES, images_root=tmp_path)

    assert len(inventory.candidates) == 1
    assert inventory.candidates[0].page_index == 0
    assert Path(inventory.candidates[0].path) == image
    assert inventory.stats["tables_total"] == 1
    assert inventory.stats["tables_usable"] == 1


def test_chart_block_becomes_candidate(tmp_path):
    """chart 之前两头都漏：不产行（本来就没正文）、也不产图，整块从流水线消失。"""
    _write_image(tmp_path, "images/c.jpg")
    path = _content_list(tmp_path, [
        {"type": "chart", "img_path": "images/c.jpg", "bbox": [100, 200, 900, 500],
         "page_idx": 0},
    ])
    inventory = build_figure_candidates(path, page_sizes=PAGE_SIZES, images_root=tmp_path)

    assert len(inventory.candidates) == 1


def test_table_without_image_warns(tmp_path):
    """表格块没有渲染图时必须出声 —— 否则用户只会看到表格缺内容。"""
    path = _content_list(tmp_path, [
        {"type": "table", "table_body": "<table></table>", "bbox": [100, 200, 900, 500],
         "page_idx": 0},
    ])
    inventory = build_figure_candidates(path, page_sizes=PAGE_SIZES, images_root=tmp_path)

    assert inventory.candidates == []
    assert inventory.stats["tables_total"] == 1
    assert inventory.stats["tables_usable"] == 0
    assert any("没拿到渲染图" in warning for warning in inventory.warnings)


def test_no_table_means_no_table_warning(tmp_path):
    """没有表格时不该出现「表格没拿到渲染图」这条告警（告警要能当信号看）。

    注意不能拿"表格"二字当判据：候选总览那条告警会顺带说明"表格/图表渲染图也在
    里面"（解释这条路的价值），那是常驻说明，不是异常。
    """
    _write_image(tmp_path)
    path = _content_list(tmp_path, [
        {"type": "image", "img_path": "images/t.jpg", "bbox": [100, 200, 900, 500],
         "page_idx": 0},
    ])
    inventory = build_figure_candidates(path, page_sizes=PAGE_SIZES, images_root=tmp_path)

    assert inventory.stats["tables_total"] == 0
    assert not any("没拿到渲染图" in warning for warning in inventory.warnings)


# ── prompt 规则 ──────────────────────────────────────────────────────


def test_prompt_table_rule_switches_by_channel():
    """通道决定表格规则：有表格图 → 只放占位符；没有 → 继续用 Markdown 抄。"""
    markdown = structure_system_prompt("物理")
    figure = structure_system_prompt("物理", tables_as_figures=True)

    assert TABLE_CLAUSE_MARKDOWN in markdown
    assert TABLE_CLAUSE_FIGURE not in markdown
    assert TABLE_CLAUSE_FIGURE in figure
    assert TABLE_CLAUSE_MARKDOWN not in figure


def test_prompt_placeholder_survives_format():
    """模板里的 JSON 花括号是转义的，加一个占位符后不能被 format 弄坏。"""
    text = structure_system_prompt("物理", tables_as_figures=True)

    assert '"stem_md"' in text
    assert "[[FIGURE_1]]" in text
    assert "{table_clause}" not in text


# ── 给模型看的行文本 ─────────────────────────────────────────────────


def _line(text: str) -> TextLine:
    return TextLine(
        line_id=7, page_index=0, y0=300.0, y1=400.0, x0=100.0, x1=500.0, text=text
    )


def test_table_html_is_masked_to_marker():
    """表格当图片时，正文里的 HTML 要压成标记 —— 否则模型会照抄出第二份残缺表格。"""
    masked = _mask_table_html(_line('<table><tr><td rowspan="3">方案一</td></tr></table>'))

    assert masked.text == "[表格]"
    # 位置一概不动：模型要靠行位置把占位符放到正确的行上
    assert (masked.line_id, masked.page_index, masked.y0, masked.y1) == (7, 0, 300.0, 400.0)


# ── 按题判断：表格规则不再全卷一票否决 ───────────────────────────────
#
# 旧实现是全局布尔：实测 9 张表里 1 张没拿到渲染图，其余 8 张有图的也被拖回
# Markdown 重抄（合并单元格必丢）。现在「只认图」按题启用，判据就是
# _tables_covered —— 它是这次修复的正确性所在，值得逐条锁住。


def test_tables_covered_when_every_table_has_figure():
    lines = [_line("<table></table>"), _line("中间还有一句话"), _line("<table></table>")]
    assert _tables_covered(lines, {1: 2}, 1) is True


def test_tables_not_covered_when_a_figure_is_missing():
    """两张表只有一张图：绝不能开「只认图」，否则没图的那张整块消失。"""
    lines = [_line("<table></table>"), _line("<table></table>")]
    assert _tables_covered(lines, {1: 1}, 1) is False


def test_tables_covered_only_counts_own_question():
    """别题的表格图不能拿来顶数 —— 计数按 qid 取。"""
    lines = [_line("<table></table>")]
    assert _tables_covered(lines, {2: 1}, 1) is False


def test_tables_covered_false_when_no_table_lines():
    """没有表格 HTML 行就不该开：开了也无事可做，还会误导 prompt。"""
    assert _tables_covered([_line("纯文字题干")], {1: 1}, 1) is False


def test_tables_covered_false_without_counts():
    """本地内嵌位图通道没有计数信息：保持 Markdown 规则，行为不变。"""
    assert _tables_covered([_line("<table></table>")], None, 1) is False


def test_mask_keeps_normal_lines_untouched():
    """普通题干一个字都不能动 —— 这个函数只在表格行上生效。"""
    line = _line("24．测量小瓷杯的密度")

    assert _mask_table_html(line) is line


def test_mask_tolerates_leading_space_and_case():
    """MinerU 的 HTML 可能带前导空白或写成大写标签。"""
    assert _mask_table_html(_line('  <TABLE><tr></tr></TABLE>')).text == "[表格]"


# ── 重抄表格的确定性兜底 ─────────────────────────────────────────────


def test_strip_markdown_table_removes_whole_block():
    """模型重抄的 Markdown 表格要整块删掉，图片引用与正文一个字不动。"""
    text = (
        "下表是小明设计的两种实验方案，请填写完整。\n"
        "\n"
        "| 实验目的 | 测量小瓷杯的密度 |\n"
        "| --- | --- |\n"
        "| 方案一 |  |\n"
        "| 器材 | 小瓷杯、量筒、水 |\n"
        "\n"
        "![figure](asset://practice/a.webp)"
    )
    stripped, count = strip_markdown_tables(text)

    assert count == 1
    assert "方案一" not in stripped          # 残缺的那份没了
    assert "| --- |" not in stripped
    assert "下表是小明设计的两种实验方案" in stripped   # 正文保留
    assert "![figure](asset://practice/a.webp)" in stripped   # 完整的图保留
    assert "\n\n\n" not in stripped          # 留下的连续空行折掉了


def test_strip_removes_table_with_multiline_cells():
    """单元格里带换行时必须**整块**删掉 —— 实测第 24 题就是这种形状。

    第一版实现按"整行含 `|`"判结束，于是在带换行的单元格处停下，把后半张表留在
    正文里变成乱码。这个用例专门锁住那次的错。
    """
    text = (
        "下表请填写完整。\n"
        "\n"
        "| 实验目的 | 测量小瓷杯的密度 |\n"
        "| --- | --- |\n"
        "| 实验步骤 | ①量筒中装适量水，体积为 $V_1$；\n"
        "②______；\n"
        "③______。 |\n"
        "| 方案二 |  |\n"
        "\n"
        "![figure](asset://practice/b.webp)"
    )
    stripped, count = strip_markdown_tables(text)

    assert count == 1
    assert "②______" not in stripped      # 半边不许留在正文里
    assert "方案二" not in stripped
    assert "下表请填写完整。" in stripped
    assert "![figure](asset://practice/b.webp)" in stripped


def test_strip_keeps_pipe_in_prose():
    """正文里出现 `|`（绝对值符号）但不是表格时不许动。"""
    text = "速度为 $|v| = 3$ m/s，方向与水平面成 30°。"

    assert strip_markdown_tables(text) == (text, 0)


def test_strip_keeps_single_row_without_separator():
    """只有一行带 `|`、没有分隔行 —— 前端也不会当表格渲染，这里同样不动。"""
    text = "甲 | 乙 两容器底面积相同。"

    assert strip_markdown_tables(text) == (text, 0)


def test_strip_handles_multiple_tables():
    text = "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n中间文字\n\n| C | D |\n|:-:|---|\n| 3 | 4 |"

    stripped, count = strip_markdown_tables(text)

    assert count == 2
    assert "中间文字" in stripped
    assert "| A |" not in stripped and "| C |" not in stripped
