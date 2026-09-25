"""插图归属的两个实测缺陷：跨题重复、空白装饰图入库。

实测样本：2022 天津和平一模。同一张运动示意图同时挂在第 3~6 题上，
另有两张 140/102 字节的空白装饰图挂在每一道题上 —— 前者导出后每题都
带着别人的图，后者让 26 道题全部标成「需复核」。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))

from physics_paper_splitter.figures import (  # noqa: E402
    BLANK_GRAY_RANGE,
    MIN_RENDERED_PX,
    FigureExtractor,
    intersect_image_rects,
    is_blank_image,
    paired_image_rects,
    sort_reading_order,
)
from physics_paper_splitter.models import CropSegment, QuestionRecord  # noqa: E402


# ── 空白装饰图 ──────────────────────────────────────────────────────


def test_pure_white_crop_is_blank():
    assert is_blank_image(Image.new("RGB", (200, 60), "white"))


def test_near_white_within_tolerance_is_blank():
    """页眉分隔线的灰度差只有个位数，按 BLANK_GRAY_RANGE 应判为空白。"""
    assert BLANK_GRAY_RANGE > 5
    image = Image.new("RGB", (200, 60), (250, 250, 250))
    image.paste((245, 245, 245), (10, 10, 190, 20))
    assert is_blank_image(image)


def test_content_image_is_not_blank():
    image = Image.new("RGB", (200, 60), "white")
    image.paste((10, 10, 10), (20, 20, 120, 40))
    assert not is_blank_image(image)


def test_tiny_crop_is_blank():
    assert is_blank_image(Image.new("RGB", (MIN_RENDERED_PX - 1, 200), "white"))


# ── 交集计算 ────────────────────────────────────────────────────────


def test_paired_rects_returns_original_and_clip():
    import pymupdf as fitz

    image_rects = [fitz.Rect(0, 0, 100, 100)]
    question_rect = fitz.Rect(50, 50, 200, 200)

    pairs = paired_image_rects(image_rects, question_rect)

    assert len(pairs) == 1
    original, clip = pairs[0]
    assert original == fitz.Rect(0, 0, 100, 100)
    assert clip == fitz.Rect(50, 50, 100, 100)
    # 兼容旧接口，仍只返回交集。
    assert intersect_image_rects(image_rects, question_rect) == [clip]


def test_small_decorative_rects_are_dropped_by_original_size():
    import pymupdf as fitz

    image_rects = [fitz.Rect(0, 0, 100, 100), fitz.Rect(10, 10, 20, 20)]
    question_rect = fitz.Rect(0, 0, 200, 200)

    assert len(paired_image_rects(image_rects, question_rect)) == 1


# ── 全局归属 ────────────────────────────────────────────────────────


class _FakePage:
    def __init__(self, images: dict[int, list]):
        self._images = images

    def get_images(self, full: bool = False):
        return [(xref,) for xref in self._images]

    def get_image_rects(self, xref: int):
        return self._images[xref]


class _FakeDoc:
    def __init__(self, pages: list[_FakePage]):
        self._pages = pages

    def __getitem__(self, index: int):
        return self._pages[index]

    @property
    def page_count(self) -> int:
        return len(self._pages)


def _record(number: int, page_index: int, rect: tuple[float, float, float, float]) -> QuestionRecord:
    x0, y0, x1, y1 = rect
    return QuestionRecord(
        number=number,
        filename=f"Q{number}.png",
        start_page=page_index,
        end_page=page_index,
        is_cross_page=False,
        segments=[CropSegment(page_index=page_index, x0=x0, y0=y0, x1=x1, y1=y1)],
    )


def test_shared_figure_belongs_to_single_question(tmp_path):
    """一张图横跨两题时只能归一道题 —— 取交集面积更大的那个。"""
    import pymupdf as fitz

    # 图占 y=100~300；题 1 只压住顶部 50 点，题 2 压住 150 点。
    page = _FakePage({7: [fitz.Rect(100, 100, 300, 300)]})
    doc = _FakeDoc([page])
    records = [
        _record(1, 0, (0, 100, 400, 150)),
        _record(2, 0, (0, 150, 400, 300)),
    ]
    extractor = FigureExtractor()

    plans = extractor._plan_ownership(doc, records)

    assert 1 not in plans
    # 归属给题 2（交集更大），但**裁切矩形是整张图**，不是交集：
    # 交集 100,150-300,300 会把图裁掉一半，详见下一个测试。
    assert [rect for _page, rect in plans[2]] == [fitz.Rect(100, 100, 300, 300)]
    assert extractor.last_shared_reassigned == 1


def test_figure_crop_is_whole_image_not_intersection():
    """裁切必须用整张图，不能只裁与题目区域的交集。

    实测教训：讲义第 55 题的原图 117x52pt 压在题目下边界上，按交集只裁到
    117x20pt（原图的 38%），落盘的是一截弧线加一条绿边 —— 复核时看着就像
    "不相干的图片进了题目"。第 36 题同理（109x50pt 只裁到 109x32pt）。
    """
    import pymupdf as fitz

    page = _FakePage({7: [fitz.Rect(100, 100, 300, 300)]})
    doc = _FakeDoc([page])
    # 题目区域只压住这张图的下半部分
    records = [_record(1, 0, (0, 150, 400, 400))]

    plans = FigureExtractor()._plan_ownership(doc, records)

    (rect,) = [rect for _page, rect in plans[1]]
    assert rect == fitz.Rect(100, 100, 300, 300), "应裁整张图"
    assert rect != fitz.Rect(100, 150, 300, 300), "不能退回交集"


def test_low_overlap_figure_is_kept_and_only_flagged():
    """低重合的插图必须**照收**，只做标记 —— 别改回"丢弃"。

    这条界线试过当过滤器，被真数据否掉了：讲义里两张跨题号边界的章节横幅
    （「随堂检测」「课堂总结」）重合 33% / 38%，而和平卷第 26 题那张跨页续页的
    真插图（两容器+弹簧+物块A）只重合 25% —— 比横幅还低。两类样本区间重叠，
    几何比例分不开，硬过滤会吃掉真图。
    """
    import pymupdf as fitz

    page = _FakePage({7: [fitz.Rect(0, 100, 400, 300)]})
    doc = _FakeDoc([page])
    # 题目区域只压住这张图顶部 20%（16000 / 80000）
    records = [_record(1, 0, (0, 100, 400, 140))]

    extractor = FigureExtractor()
    plans = extractor._plan_ownership(doc, records)

    assert 1 in plans, "低重合的图也必须保留"
    assert extractor.last_low_overlap == {1: 1}, "但必须被标记出来"


def test_tie_falls_back_to_lower_question_number():
    import pymupdf as fitz

    page = _FakePage({3: [fitz.Rect(0, 100, 100, 200)]})
    doc = _FakeDoc([page])
    records = [
        _record(9, 0, (0, 100, 100, 150)),
        _record(4, 0, (0, 150, 100, 200)),
    ]

    plans = FigureExtractor()._plan_ownership(doc, records)

    assert 4 in plans and 9 not in plans


def test_plan_order_is_stable_across_pages():
    import pymupdf as fitz

    pages = [
        _FakePage({1: [fitz.Rect(0, 400, 100, 500)]}),
        _FakePage({2: [fitz.Rect(0, 10, 100, 100)]}),
    ]
    doc = _FakeDoc(pages)
    records = [
        _record(1, 0, (0, 0, 200, 600)),
        _record(2, 1, (0, 0, 200, 200)),
    ]

    plans = FigureExtractor()._plan_ownership(doc, records)

    assert [page_index for page_index, _clip in plans[1]] == [0]
    assert [page_index for page_index, _clip in plans[2]] == [1]


# ── 阅读顺序（行 → 列）──────────────────────────────────────────────
# 下面三条都是 2026 河东一模实测出来的：并排图块的 y0 只差几个点，而 x 差上百点，
# 旧的 (page, y0, x0) 字典序会把左右顺序排乱。


def test_side_by_side_figures_are_ordered_left_to_right():
    """题16：原卷顺序是「北极熊 → 电路甲 → 电压表」，字典序排成了「电路 → 北极熊 → 电压表」。"""
    import pymupdf as fitz

    entries = [
        (0, fitz.Rect(269.9, 520.3, 380.0, 600.0), "电路甲"),
        (0, fitz.Rect(108.6, 527.5, 260.0, 610.0), "北极熊"),
        (0, fitz.Rect(364.0, 528.3, 500.0, 605.0), "电压表"),
    ]

    assert [payload for _page, _rect, payload in sort_reading_order(entries)] == [
        "北极熊", "电路甲", "电压表",
    ]


def test_rows_are_ordered_top_to_bottom_then_left_to_right():
    """题21：图例在上一行，甲/乙/丙在下一行；行间按 y、行内按 x。

    旧字典序把这一列排成了「图例 → 乙 → 甲 → 丙」（乙的 y0 比甲小 6.7pt）。
    """
    import pymupdf as fitz

    entries = [
        (0, fitz.Rect(425.1, 112.0, 479.2, 146.5), "图例"),
        (0, fitz.Rect(85.7, 163.3, 241.1, 236.6), "甲"),
        (0, fitz.Rect(246.5, 156.6, 395.3, 235.7), "乙"),
        (0, fitz.Rect(420.9, 175.1, 483.4, 221.4), "丙"),
    ]

    assert [payload for _page, _rect, payload in sort_reading_order(entries)] == [
        "图例", "甲", "乙", "丙",
    ]


def test_shallow_overlap_does_not_join_the_row():
    """竖直重叠不足较矮那块一半时不算同一行。

    否则这条贴着高图块下缘的细条（x 在左）会被并进同一行，按 x 排到高图块**前面**。
    """
    import pymupdf as fitz

    entries = [
        (0, fitz.Rect(0, 290, 100, 310), "细条"),        # 与高图块只重叠 10pt
        (0, fitz.Rect(300, 100, 500, 300), "高图块"),     # 高 200pt
    ]

    assert [payload for _page, _rect, payload in sort_reading_order(entries)] == [
        "高图块", "细条",
    ]


def test_candidate_figures_are_written_in_reading_order(tmp_path):
    """MinerU 路径：并排图块按左→右落盘成 Q0NN_01/02/03。

    这条同时盯着两个踩过的坑：

    ① `sort_reading_order` 返回的是 (page, rect, **payload**) 元组，调用方必须把 payload
       解出来。曾经直接把元组当 FigureCandidate 用 —— `candidate.path` 抛 AttributeError，
       被落盘循环的 except 吞成 unreadable，**整题的插图全丢**，界面上只留一句
       「有 N 张 MinerU 插图读取失败或为空白，已跳过」。`unreadable == 0` 就是拦这个。
    ② 并排图块的 y0 只差几个点（实测题16：520.3 / 527.5 / 528.3），而 x 差上百点。
       旧字典序会排成「电路 → 北极熊 → 电压表」，与原卷顺序相反。
    """
    from physics_paper_splitter.figures import FigureCandidate, extract_candidate_figures

    # 三张可分辨的假图，用高度区分谁是谁；y0 只差几个点、x 差上百点
    specs = [
        (269.9, 520.3, 30),   # 电路甲：y0 最小，旧排序会把它排到第一
        (108.6, 527.5, 10),   # 北极熊：x 最左
        (364.0, 528.3, 20),   # 电压表：x 最右
    ]
    candidates = []
    for x0, y0, height in specs:
        source = tmp_path / f"src_{int(x0)}.png"
        image = Image.new("RGB", (60, height), "white")
        image.paste("black", (0, 0, 30, max(1, height // 2)))   # 非纯色，免得被判空白
        image.save(source)
        candidates.append(FigureCandidate(0, x0, y0, x0 + 60, y0 + 60, source))

    record = _record(16, 0, (0.0, 500.0, 500.0, 620.0))
    figures_dir = tmp_path / "figures"

    result = extract_candidate_figures([record], candidates, figures_dir)

    assert result.unreadable == 0, "候选读不出来 → payload 没从 (page, rect, payload) 里解出来"
    names = [Path(name).name for name in result.figures[16]]
    assert names == ["Q016_01.webp", "Q016_02.webp", "Q016_03.webp"]
    sizes = [Image.open(figures_dir / name).size for name in names]
    assert sizes == [(60, 10), (60, 30), (60, 20)]   # 北极熊 → 电路甲 → 电压表


def test_blank_figure_is_not_written(tmp_path, monkeypatch):
    """空白装饰图必须在落盘前被丢弃，且不占用序号。"""
    import pymupdf as fitz

    # 两张独立插图：第一张空白（页眉分隔线），第二张有内容。
    page = _FakePage({5: [fitz.Rect(0, 0, 200, 100)], 6: [fitz.Rect(0, 100, 200, 200)]})
    doc = _FakeDoc([page])
    records = [_record(1, 0, (0, 0, 300, 300))]
    extractor = FigureExtractor()

    rendered: list[Image.Image] = [
        Image.new("RGB", (200, 60), "white"),  # 空白，应被丢
        Image.new("RGB", (200, 60), "white"),
    ]
    rendered[1].paste((0, 0, 0), (10, 10, 100, 40))  # 第二张有内容
    monkeypatch.setattr(
        extractor._cropper, "_render_segment", lambda page, rect: rendered.pop(0)
    )

    result = extractor.extract_all(doc, records, tmp_path)

    assert result[1] == ["figures/Q001_01.webp"]
    assert extractor.last_blank_dropped == 1
    assert (tmp_path / "Q001_01.webp").exists()
    assert not (tmp_path / "Q001_02.webp").exists()


# ── 跨页复现的装饰图 ────────────────────────────────────────────────


def test_recurring_xref_is_filtered():
    """同一图片对象出现在 3 页以上即为页眉/水印/logo，不进任何题目。

    实测和平卷 3 个 xref 出现在全部 38 页，逐页裁出重复内容挂到 10 道题上。
    """
    import pymupdf as fitz

    from physics_paper_splitter.figures import RECURRING_PAGE_MIN, recurring_xrefs

    strip = fitz.Rect(0, 0, 700, 45)
    figure = fitz.Rect(50, 200, 250, 400)
    pages = [
        _FakePage({300: [strip], 11: [figure]}),
        _FakePage({300: [strip]}),
        _FakePage({300: [strip]}),
    ]
    doc = _FakeDoc(pages)

    assert RECURRING_PAGE_MIN == 3
    assert recurring_xrefs(doc) == {300}

    records = [_record(1, 0, (0, 0, 700, 500))]
    extractor = FigureExtractor()
    plans = extractor._plan_ownership(doc, records, recurring=recurring_xrefs(doc))

    assert [clip for _page, clip in plans[1]] == [figure]
    assert extractor.last_recurring_dropped == 1  # 按图片对象去重


def test_recurring_filter_runs_inside_extract_all(tmp_path, monkeypatch):
    """extract_all 必须自己算跨页复现，不能依赖调用方传参。"""
    import pymupdf as fitz

    strip = fitz.Rect(0, 0, 700, 45)
    content = fitz.Rect(50, 200, 250, 400)
    pages = [
        _FakePage({300: [strip], 11: [content]}),
        _FakePage({300: [strip]}),
        _FakePage({300: [strip]}),
    ]
    doc = _FakeDoc(pages)
    records = [_record(1, 0, (0, 0, 700, 500))]
    extractor = FigureExtractor()

    def fake_render(page, rect):
        image = Image.new("RGB", (200, 60), "white")
        image.paste((0, 0, 0), (10, 10, 100, 40))
        return image

    monkeypatch.setattr(extractor._cropper, "_render_segment", fake_render)

    result = extractor.extract_all(doc, records, tmp_path)

    assert result[1] == ["figures/Q001_01.webp"]
    assert extractor.last_recurring_dropped == 1


# ── 跨页复现的装饰图 ────────────────────────────────────────────────


def test_recurring_xref_is_filtered():
    """同一图片对象出现在 3 页以上即为页眉/水印/logo，不进任何题目。

    实测和平卷 3 个 xref 出现在全部 38 页，逐页裁出重复内容挂到 10 道题上。
    """
    import pymupdf as fitz

    from physics_paper_splitter.figures import RECURRING_PAGE_MIN, recurring_xrefs

    strip = fitz.Rect(0, 0, 700, 45)
    figure = fitz.Rect(50, 200, 250, 400)
    pages = [
        _FakePage({300: [strip], 11: [figure]}),
        _FakePage({300: [strip]}),
        _FakePage({300: [strip]}),
    ]
    doc = _FakeDoc(pages)

    assert RECURRING_PAGE_MIN == 3
    assert recurring_xrefs(doc) == {300}

    records = [_record(1, 0, (0, 0, 700, 500))]
    extractor = FigureExtractor()
    plans = extractor._plan_ownership(doc, records, recurring=recurring_xrefs(doc))

    assert [clip for _page, clip in plans[1]] == [figure]
    assert extractor.last_recurring_dropped == 1  # 按图片对象去重


def test_recurring_filter_runs_inside_extract_all(tmp_path, monkeypatch):
    """extract_all 必须自己算跨页复现，不能依赖调用方传参。"""
    import pymupdf as fitz

    strip = fitz.Rect(0, 0, 700, 45)
    content = fitz.Rect(50, 200, 250, 400)
    pages = [
        _FakePage({300: [strip], 11: [content]}),
        _FakePage({300: [strip]}),
        _FakePage({300: [strip]}),
    ]
    doc = _FakeDoc(pages)
    records = [_record(1, 0, (0, 0, 700, 500))]
    extractor = FigureExtractor()

    def fake_render(page, rect):
        image = Image.new("RGB", (200, 60), "white")
        image.paste((0, 0, 0), (10, 10, 100, 40))
        return image

    monkeypatch.setattr(extractor._cropper, "_render_segment", fake_render)

    result = extractor.extract_all(doc, records, tmp_path)

    assert result[1] == ["figures/Q001_01.webp"]
    assert extractor.last_recurring_dropped == 1
