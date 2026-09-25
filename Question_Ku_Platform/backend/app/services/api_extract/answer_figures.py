"""答案区插图归属与裁切。

**为什么需要这个模块**：`FigureExtractor` 只处理正文题目记录
（`QuestionRecord.segments`），答案区（第 question_page_count+1 页起）从来没进过
抽取范围。后果是「答案本身是图」的题在产物里连图都没有：

- 和平卷第 20 题：卷面「【答案】」下面就是一幅标了 R₁=15Ω、R₂=10Ω 的电路图，
  文字侧为空，answer 字段只能是空的；
- 第 26 题 (1)：答案「如图」，指的是答案区重印题干上方那张受力分析图；
- 第 24 题 (2)(3)：答案「如上图所示」「如上图2 所示」。

**只抽需要的题**：答案是纯文字的题一律不抽。否则答案区重印的题干配图会被
当成答案图，26 道题每题都挂上一张，既浪费又误导。

**只抽题号唯一的题**：答案区里同一题号出现多次意味着文档分板块重新编号
（讲义的「例题解析 / 随堂检测」各自从 1 开始），此时整数题号无法确定归属，
直接放弃 —— 与 `resolve_answers` 里 ambiguous 的处理口径一致。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf as fitz

from physics_paper_splitter.answers import (
    BLOCK_MARKER_RE,
    STRONG_ANCHOR_RE,
    WEAK_ANCHOR_RE,
)
from physics_paper_splitter.cropper import QuestionCropper, save_webp
from physics_paper_splitter.figures import (
    FIGURE_MIN_SIZE_PT,
    is_blank_image,
    recurring_xrefs,
)
from physics_paper_splitter.lines import TextLine

# 答案里出现这些词，说明答案是图或答案依赖图。
FIGURE_ANSWER_WORDS = (
    "如上图",
    "如图",
    "见图",
    "图略",
    "图甲",
    "图乙",
    "图丙",
    "如上图2",
)

# 答案文本里的小问编号：（1）、(2)，不含「图1」这类非括号引用。
SUB_QUESTION_RE = re.compile(r"[（(]\s*(\d{1,2})\s*[）)]")


def answer_needs_figures(answer: str | None, has_sources: bool) -> bool:
    """这道题的答案要不要配图。

    answer 为空但有答案来源，说明在答案区找到了该题解析、只是答案字段没有
    文字 —— 卷面答案不是图就是表格，同样需要看图。
    """
    text = (answer or "").strip()
    if not text:
        return has_sources
    return any(word in text for word in FIGURE_ANSWER_WORDS)


def answer_region_blocks(lines: list[TextLine]) -> list[tuple[int, list[TextLine]]]:
    """按题号锚点把答案区切成 [(题号, 该题的行)]。

    锚点复用 packages 的强/弱锚点：强锚点（题号 + 分值括号）允许出现在行内
    任意位置（公式乱码会把题号挤进长行深处），未命中时回退行首弱锚点。
    """
    blocks: list[tuple[int, list[TextLine]]] = []
    current: tuple[int, list[TextLine]] | None = None
    for line in lines:
        strong = STRONG_ANCHOR_RE.search(line.text)
        weak = WEAK_ANCHOR_RE.match(line.text) if strong is None else None
        match = strong or weak
        if match:
            if current is not None:
                blocks.append(current)
            current = (int(match.group(1)), [line])
            continue
        if current is not None:
            current[1].append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def _block_markers(block_lines: list[TextLine]) -> list[tuple[int, float, float, str]]:
    """一道题解析块里的段落标记行，按 (页, y) 排序。

    返回 (页序, y0, y1, kind)，kind 为 "answer"（【答案】）或 "other"
    （【分析】【解答】【点评】等）。这是区分「答案区的图」和「解答推导图」
    的坐标系：一张图紧邻【答案】标记 → 答案区配图；夹在【解答】与【点评】
    之间的图 → 推导过程图（实测和平卷第 20 题同一页两种图并存）。
    """
    markers: list[tuple[int, float, float, str]] = []
    for line in block_lines:
        match = BLOCK_MARKER_RE.search(line.text)
        if not match:
            continue
        kind = "answer" if "答案" in match.group(0) else "other"
        markers.append((line.page_index, line.y0, line.y1, kind))
    markers.sort(key=lambda item: (item[0], item[1]))
    return markers


def _adjacent_to_answer_marker(
    markers: list[tuple[int, float, float, str]], page_index: int, rect: fitz.Rect
) -> bool:
    """图是否紧邻【答案】标记：与标记行重叠，或两侧最近的段落标记之一是它。

    与【答案】行纵向重叠是常见排版（图压着标记行，浮动锚点漂移），直接算紧邻；
    否则看图上方最近、下方最近的标记 —— 只有【答案】标记直接贴着图（中间没有
    隔别的标记）才算。隔着【分析】/【解答】的图是推导图，不算。
    """
    overlapping = any(
        marker[0] == page_index
        and marker[3] == "answer"
        and not (marker[2] <= rect.y0 or marker[1] >= rect.y1)
        for marker in markers
    )
    if overlapping:
        return True
    prev_marker = next(
        (
            marker
            for marker in reversed(markers)
            if (marker[0], marker[2]) <= (page_index, rect.y0)
        ),
        None,
    )
    if prev_marker is not None and prev_marker[3] == "answer":
        return True
    next_marker = next(
        (
            marker
            for marker in markers
            if (marker[0], marker[1]) >= (page_index, rect.y1)
        ),
        None,
    )
    return next_marker is not None and next_marker[3] == "answer"


def plan_answer_figures(
    doc: fitz.Document,
    answer_lines: list[TextLine],
    wanted_numbers: set[int],
    *,
    # 与正文插图抽取同一个阈值：窄高实拍图（如手机 28×56pt）也要裁出来，
    # 用装饰碎片那个 40pt 会把它们吃掉 —— 详见 figures.py 里 FIGURE_MIN_SIZE_PT。
    min_size_pt: float = FIGURE_MIN_SIZE_PT,
    stem_xrefs: dict[int, set[int]] | None = None,
) -> tuple[dict[int, list[tuple[int, fitz.Rect]]], dict[int, set[int]]]:
    """排定「答案区哪张图归哪道题」，返回 (题号 -> [(页序, 裁切矩形)], 题干图重印)。

    归属判据是「图的矩形与该题行区间所在页面条带有交集」，取**整张图**而不是
    交集 —— 答案是图的题，图常排在【答案】标记上方（PDF 浮动对象锚点漂移），
    与条带只重叠几个点，用交集会把图裁成一条缝。

    `stem_xrefs`（题号 -> 该题题干图的 xref）用来剔除**重复裁图**：答案区常常
    重印题干配图作为讲解背景（实测和平卷第 24 题把题干 3 张图全重印了一遍），
    这些图题干里已经裁过、也已挂在 `figures` 上，答案区再裁一份纯属重复。
    判据是 xref 相同（同一个图对象被两处引用），不做视觉相似度推断。

    **答案区优先**：一道题的解析块（【答案】…【点评】）里可能既有答案图又有
    解答推导图（实测和平卷第 20 题：【答案】标记旁是 R₁/R₂ 电路图，而【解答】
    正文里还有"图甲/图乙/图丙"推导图）。判据是图是否紧邻【答案】标记
    （`_adjacent_to_answer_marker`）：答案区有图就只输出答案区的图，不把推导
    图掺进来 —— 答案区没图（靠「如上图所示」引导才取图的题，如第 24 题）才
    退回整块条带取图。
    """
    recurring = recurring_xrefs(doc)
    blocks = answer_region_blocks(answer_lines)
    occurrences = Counter(number for number, _ in blocks)

    plans: dict[int, list[tuple[int, fitz.Rect]]] = {}
    reused: dict[int, set[int]] = {}
    claimed_xrefs: set[int] = set()
    for number, block_lines in blocks:
        if number not in wanted_numbers or occurrences[number] != 1:
            continue
        stem_reuse = (stem_xrefs or {}).get(number, frozenset())
        markers = _block_markers(block_lines)
        near: list[tuple[int, fitz.Rect]] = []
        far: list[tuple[int, fitz.Rect]] = []
        by_page: dict[int, list[TextLine]] = {}
        for line in block_lines:
            by_page.setdefault(line.page_index, []).append(line)
        page_indexes = sorted(by_page)
        last_position = len(page_indexes) - 1
        for position, page_index in enumerate(page_indexes):
            page = doc[page_index]
            page_lines = by_page[page_index]
            top = min(line.y0 for line in page_lines)
            bottom = max(line.y1 for line in page_lines)
            # 跨页题的行区间不能只看本页的行：答案图常排在【答案】标记上方
            # （PDF 浮动对象锚点漂移），只按本页行范围切会把它整张漏掉。
            # 起始页取锚点行到页底、结束页取页顶到末行、中间页整页。
            if last_position == 0:
                y0, y1 = top, bottom
            elif position == 0:
                y0, y1 = top, page.rect.height
            elif position == last_position:
                y0, y1 = 0.0, bottom
            else:
                y0, y1 = 0.0, page.rect.height
            band = fitz.Rect(0.0, y0, page.rect.width, y1)

            for image_info in page.get_images(full=True):
                xref = image_info[0]
                if xref in recurring or xref in claimed_xrefs:
                    continue
                try:
                    rects = page.get_image_rects(xref)
                except Exception:
                    # 被遮罩或损坏的图片对象取不到矩形，跳过不影响其余。
                    continue
                for raw_rect in rects:
                    image_rect = fitz.Rect(raw_rect)
                    if image_rect.width < min_size_pt or image_rect.height < min_size_pt:
                        continue
                    if (image_rect & band).is_empty:
                        continue
                    # 同一图片对象被多页/多处引用时只归一次，否则答案是图的题
                    # 会挂上三张一模一样的图（实测和平卷第 20 题的 xref135
                    # 在答案页与末页各出现一次）。
                    claimed_xrefs.add(xref)
                    if xref in stem_reuse:
                        # 题干图在答案区的重印：题干里已裁过，这里只登记不裁。
                        reused.setdefault(number, set()).add(xref)
                        continue
                    bucket = (
                        near
                        if _adjacent_to_answer_marker(markers, page_index, image_rect)
                        else far
                    )
                    bucket.append((page_index, image_rect))
        # 答案区（【答案】标记旁）有图 → 只用它；没有 → 靠答案文字的
        # 「如上图所示」引导取【分析】/【解答】里的图（第 24 题的情形）。
        for item in near or far:
            plans.setdefault(number, []).append(item)

    for number in plans:
        plans[number].sort(key=lambda item: (item[0], item[1].y0, item[1].x0))
    return plans, reused


def plan_stem_figure_refs(
    reused: dict[int, set[int]],
    kept: dict[int, list[str]],
    figure_names: dict[int, dict[int, str]],
    figure_indexes: dict[int, dict[int, int]],
) -> dict[int, list[dict]]:
    """「答案就是题干那张图」的题：标注指向题干图，不再裁一份。

    判据是**排除重印件后一张答案图都不剩**（`number not in kept`）。这类题
    卷面的答案就是「如图」，指的就是题干配图 —— 答案区把它重印了一遍当讲解
    背景，而题干里早就裁过并挂在 `figures` 上了。

    只要该题还留着哪怕一张真正的新图（如和平卷第 24 题分析区里的 (2) 电路图、
    (3) 描点图象），就**不**产出 ref：那说明「如上图所示」指的是新图，
    再标一句「见题干图」反而把人指错。

    Args:
        reused: 题号 -> 被判定为重印件而排除的 xref 集合。
        kept: 题号 -> 已裁出的答案图相对路径（`answer_figures` 的产出）。
        figure_names: 题号 -> {xref: 题干图相对路径}。
        figure_indexes: 题号 -> {xref: 它在题干图里的序号，从 1 起}。

    Returns:
        题号 -> `[{"stem_figure": "figures/Q0NN_MM.webp", "stem_index": N}]`，
        只含真正需要标注的题；xref 排序保证输出稳定（便于比对与测试）。
    """
    refs_by_number: dict[int, list[dict]] = {}
    for number, xrefs in reused.items():
        if number in kept:
            # 该题还有新裁的答案图，题干图重印只是背景，不需要指路。
            continue
        names = figure_names.get(number, {})
        indexes = figure_indexes.get(number, {})
        refs = [
            {"stem_figure": names[xref], "stem_index": indexes[xref]}
            for xref in sorted(xrefs)
            if xref in names and xref in indexes
        ]
        if refs:
            refs_by_number[number] = refs
    return refs_by_number


def extract_answer_figures(
    doc: fitz.Document,
    plans: dict[int, list[tuple[int, fitz.Rect]]],
    figures_dir: Path,
    *,
    dpi: int = 300,
    webp_quality: int = 92,
) -> dict[int, list[str]]:
    """按排定结果裁出答案插图，命名 answer_Q0NN_MM.webp，与正文插图区分开。"""
    if not plans:
        return {}
    figures_dir.mkdir(parents=True, exist_ok=True)
    cropper = QuestionCropper(dpi=dpi, webp_quality=webp_quality)
    results: dict[int, list[str]] = {}
    for number, entries in plans.items():
        paths: list[str] = []
        index = 0
        for page_index, clip in entries:
            image = cropper._render_segment(doc[page_index], clip)
            if is_blank_image(image):
                continue
            index += 1
            name = f"answer_Q{number:03d}_{index:02d}.webp"
            save_webp(image, figures_dir / name, webp_quality)
            paths.append(f"figures/{name}")
        if paths:
            results[number] = paths
    return results


def split_answer_blocks(answer: str | None) -> list[dict]:
    """把多小问答案文本切成 [{label, text, figures}] 块，figures 初始为空。

    「（2）如上图所示；（3）如上图2 所示」这类答案要能把图挂到对应小问下，
    笼统挂在题级、人得自己对顺序。没有小问结构（纯一段或为空）时返回单个
    label=None 的块或空列表，调用方据此决定走不走分块渲染。
    """
    text = (answer or "").strip()
    if not text:
        return []
    matches = list(SUB_QUESTION_RE.finditer(text))
    if not matches:
        return [{"label": None, "text": text, "figures": []}]
    blocks: list[dict] = []
    lead = text[: matches[0].start()].strip()
    if lead:
        # 「答：」这类前导词单独成块，不属于任何小问。
        blocks.append({"label": None, "text": lead, "figures": []})
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(
            {
                "label": f"（{match.group(1)}）",
                "text": text[match.start() : end].strip(),
                "figures": [],
            }
        )
    return blocks


def assign_answer_figures(blocks: list[dict], figures: list[str]) -> list[dict]:
    """把答案插图按顺序分给含「如图/如上图」引导的小问块（原地修改并返回）。

    卷面的写法是小问按顺序引用图（第 24 题 (2)「如上图所示」→ 电路图、
    (3)「如上图2 所示」→ 描点图象），与 `extract_answer_figures` 的页内从上到下
    排序一致，所以按出现顺序一对一分配。分不完的图挂到最后一个目标块，
    不丢弃 —— 宁可多挂一张让人核对，也不能悄悄少一张。
    """
    if not figures or not blocks:
        return blocks
    targets = [
        block
        for block in blocks
        if block["label"] and any(word in block["text"] for word in FIGURE_ANSWER_WORDS)
    ]
    if not targets:
        # 没有小问级的引导词（答案整段「如图」或为空），挂到第一个块。
        targets = blocks[:1]
    queue = list(figures)
    for block in targets:
        if not queue:
            break
        block["figures"].append(queue.pop(0))
    if queue:
        targets[-1]["figures"].extend(queue)
    return blocks
