"""插图落到选项上：A/B/C/D 就是四张电路图时，别把图全堆到题干末尾。

实测动机（2026-09-24，2026 河东区一模 题5）：卷面上的「图3」是四个电路图并排、
每个图下方标着 A/B/C/D。切题把这一张图切成了 4 张插图，那四个字母被当成选项
标签 —— 原逻辑于是把 4 张图全追加到题干末尾、4 个选项内容全空。界面上看到的
就是「四张没有标记的电路图 + A. B. C. D. 四个空选项」，图文完全对不上。

绑定要三条同时成立，宁可不做也不能把图配错：
选项 ≥2、每个选项都有标签且内容为空、插图数与选项数相等。
"""

from __future__ import annotations

# 先 import api_extract，触发 packages/ 的 sys.path 注入。
from app.services.api_extract import ExtractCancelled  # noqa: F401
from app.services.api_extract.structure import inline_figures


def _link(path: str) -> str:
    return f"![figure](asset://{path})"


def test_label_only_options_get_one_figure_each():
    """四个字母选项 + 四张图 → 第 i 张图落到第 i 个选项，题干不再堆图。"""
    figures = [f"figures/Q005_0{i}.webp" for i in range(1, 5)]
    options = [{"label": label, "content": ""} for label in "ABCD"]

    stem, opts, placed = inline_figures("下列电路图符合题意的是", options, figures)

    assert placed == len(figures)
    assert stem == "下列电路图符合题意的是"
    assert [option["content"] for option in opts] == [_link(path) for path in figures]
    assert [option["label"] for option in opts] == list("ABCD")


def test_binding_keeps_option_order_not_figure_index_order():
    """绑定按选项顺序，不按图在页面上的先后重排 —— 第 i 个选项就要第 i 张图。"""
    figures = ["figures/c.webp", "figures/a.webp"]
    options = [{"label": "A", "content": ""}, {"label": "B", "content": ""}]

    _stem, opts, _placed = inline_figures("题干", options, figures)

    assert opts[0]["content"] == _link("figures/c.webp")
    assert opts[1]["content"] == _link("figures/a.webp")


def test_content_equal_to_label_counts_as_empty():
    """模型常把图下的字母同时写进 label 和 content —— 那同样是没有信息的占位。

    实测题5 的选项就是 {'label': 'A', 'content': 'A'}。漏掉这种写法，这道题就还是
    「四张无标记的电路图 + 四个字母选项」，图文依旧对不上。
    """
    figures = [f"figures/Q005_0{i}.webp" for i in range(1, 5)]
    options = [{"label": label, "content": label} for label in "ABCD"]

    stem, opts, placed = inline_figures("下列电路图符合题意的是", options, figures)

    assert placed == 4
    assert [option["content"] for option in opts] == [_link(path) for path in figures]
    assert stem == "下列电路图符合题意的是"    # 字母占位被图替换，不再堆在题干末尾


def test_option_with_text_disables_binding():
    """只要有一个选项带内容，就说明这是文字选项，不能按图绑定。"""
    figures = ["figures/a.webp", "figures/b.webp"]
    options = [{"label": "A", "content": ""}, {"label": "B", "content": "乙球质量更大"}]

    stem, opts, placed = inline_figures("题干", options, figures)

    assert opts[1]["content"] == "乙球质量更大"
    assert placed == 0                       # 图没落在选项里
    assert stem.count("![figure]") == 2      # 退回旧行为：追加到题干末尾


def test_count_mismatch_keeps_old_behaviour():
    """插图数与选项数不等 → 不做绑定（少一张就可能配错位）。"""
    figures = ["figures/a.webp", "figures/b.webp", "figures/c.webp"]
    options = [{"label": label, "content": ""} for label in "AB"]

    stem, opts, _placed = inline_figures("题干", options, figures)

    assert all(option["content"] == "" for option in opts)
    assert stem.count("![figure]") == 3


def test_single_option_is_not_treated_as_figure_options():
    """只有一个选项时不绑定 —— 那种情况多半是模型只吐了半个选项表。"""
    figures = ["figures/a.webp"]
    options = [{"label": "A", "content": ""}]

    stem, opts, _placed = inline_figures("题干", options, figures)

    assert opts[0]["content"] == ""
    assert stem.count("![figure]") == 1


def test_placeholder_replacement_still_works():
    """回归护栏：题干占位符按序替换、多余的图追加到末尾的既有行为不变。"""
    figures = ["figures/a.webp", "figures/b.webp"]
    stem, opts, placed = inline_figures("如图 [[FIGURE_1]] 所示，还有 [[FIGURE_2]]", [], figures)

    assert placed == 2
    assert stem == f"如图 {_link('figures/a.webp')} 所示，还有 {_link('figures/b.webp')}"
    assert opts == []
