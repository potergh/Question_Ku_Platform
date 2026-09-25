from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from .cropper import QuestionCropper, save_webp
from .models import QuestionRecord

# 宽或高小于该值（PDF 点）的图片视为装饰碎片（项目符号、边框），不参与版面判定。
# 使用者：边界判定 _figures_in_band —— 那一侧要的是"这里有没有一张像样的图"，
# 碎片图进来只会干扰题号定位，所以这里保持 40 不动。
DEFAULT_MIN_SIZE_PT = 40.0

# 插图抽取专用阈值：比上面的装饰判定**宽松一半**。
# 区别在于后果：边界判定放进一张碎片图只是多一条噪声，而插图抽取丢掉一张真图
# 就是这道题永久缺一张图。实测南开卷 #7 的手机配图版面上只有 28×56pt（窄高实拍），
# 按 40 判会被当装饰丢掉，D 选项整题没图；降到 20 后正常裁出（116×232px）。
# 20pt ≈ 7mm：项目符号（~8pt）与边框线（1~2pt）仍在被剔除的一侧。
FIGURE_MIN_SIZE_PT = 20.0

# 裁出来后灰度极差小于该值即视为空白（页眉分隔线、纯色块、被白边吃掉的残图）。
# 实测这类图编码后只有 100~150 字节，却会挂在每一道题上触发「需复核」。
BLANK_GRAY_RANGE = 12.0
# trim 白边后比这还小的图没有内容。
MIN_RENDERED_PX = 8

# 同一个图片对象出现在这么多页以上，就是页眉/页脚/水印/logo，不是题目插图。
# 实测和平卷有 3 个 xref 出现在全部 38 页（714x45pt 水印条、两个二维码），
# 它们逐页被裁出重复内容，挂到了 10 道题上。真·题目插图最多跨 2 页。
RECURRING_PAGE_MIN = 3

# 重合比例低于此值的插图会被**标记出来**（不是丢弃），提醒人工核对。
#
# 为什么只告警不丢弃 —— 这条界线试过当过滤器，被真数据否决了：
#   讲义：33 张图完全落在题目区域内，两张跨在题号边界上的章节横幅
#        （「随堂检测」「课堂总结」）只重合 33% / 38%；
#   和平卷：第 26 题是跨页题，续页那张"两容器+弹簧+物块A"的图只重合 25%
#        —— 它是**真插图**，比两张横幅还低。
# 两类样本的区间互相重叠（25% 真图 vs 33% 横幅），几何比例分不开它们。
# 硬过滤会吃掉和平卷的真图，所以这里只做提示：横幅该由人一眼认出来删掉，
# 而误判的代价从"丢一张真图"降为"多看一眼"。
LOW_OVERLAP_WARN_RATIO = 0.5

# 行分组阈值：两块在竖直方向的重叠要超过**较矮那块**高度的一半，才算落在同一行。
# 取 0.5 而不是"有一点重叠就算"：页面上一个细长的图例条正好垫在高图块的边缘时，
# 不该被并进同一行。
ROW_OVERLAP_RATIO = 0.5


def sort_reading_order(entries: list[tuple[int, fitz.Rect, object]]):
    """把 (page_index, rect, payload) 按阅读顺序排列，返回新列表。

    **为什么不能用 (page, y0, x0) 字典序**：同一行的几个图块，y0 常常只差几个点，
    而 x 差上百点 —— y0 优先会把左右顺序彻底打乱。2026 河东一模实测：

    - 题16 三个图块 y0 = 553.1 / 560.7 / 561.6，x = 115.5 / 286.9 / 387.0。
      按 y0 排出来是「电路 → 北极熊 → 电压表」，与原卷的「北极熊 → 电路 → 电压表」相反。
    - 题5 的四个电路图 y0 只有 369.6 与 370.4 两个值，被交错成 1、3、2、4。
    - 题21 的甲/乙同样因为 y0 差 6.7pt 而写成了「乙 在 甲 前」。

    正确口径是「先按行分组，行内按 x，行间按 y」。行按 y0 升序生成、
    行内按 x0 升序，保证输出的阅读顺序与人翻页时的顺序一致。
    """
    by_page: dict[int, list] = {}
    for entry in entries:
        by_page.setdefault(entry[0], []).append(entry)

    ordered: list = []
    for page_index in sorted(by_page):
        rows: list[dict] = []
        # 按 y0 升序扫描：新区块要么并进已有行，要么自成一行（新行必然在下方）。
        for entry in sorted(by_page[page_index], key=lambda item: item[1].y0):
            rect = entry[1]
            for row in rows:
                overlap = min(row["y1"], rect.y1) - max(row["y0"], rect.y0)
                shorter = min(row["y1"] - row["y0"], rect.height)
                if shorter > 0 and overlap > shorter * ROW_OVERLAP_RATIO:
                    row["y0"] = min(row["y0"], rect.y0)
                    row["y1"] = max(row["y1"], rect.y1)
                    row["items"].append(entry)
                    break
            else:
                rows.append({"y0": rect.y0, "y1": rect.y1, "items": [entry]})
        for row in rows:
            ordered.extend(sorted(row["items"], key=lambda item: item[1].x0))
    return ordered


@dataclass(frozen=True, slots=True)
class FigureCandidate:
    """外部提供的插图候选：哪一页、哪块矩形、图片文件在哪。

    存在的理由：FigureExtractor 只能从页面上找**内嵌位图**，而讲义/学案这类
    Word 导出件里的插图多是**矢量线条画**（容器、电路、光路），一张都找不到
    —— 实测某讲义 75 题只抽到 36 张。MinerU 按版面分析切区域再渲染，矢量图
    也在里面（同一份 79 张）。所以这类文档把"图从哪来"换成 MinerU 的图块，
    归属与落盘仍走本模块这套口径。
    """

    page_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    path: Path
    # 产生该候选的 MinerU 块类型（image / chart / table）。下游要靠它知道
    # 「这道题有几个表格块拿到了渲染图」—— 这是按题启用「表格只认图」规则的
    # 依据。默认 "image"：本地内嵌位图路径不区分类型，保持向后兼容。
    kind: str = "image"

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)


@dataclass(slots=True)
class CandidateFigureResult:
    """外部候选落盘的结果。"""

    figures: dict[int, list[str]] = field(default_factory=dict)
    # 题号 -> 重合比例过低的张数（照收，只标记，与位图路径同一口径）。
    low_overlap: dict[int, int] = field(default_factory=dict)
    # 读不出来的候选：不静默吞掉，由调用方写进告警。
    unreadable: int = 0
    # 题号 -> 成功落盘的表格渲染图张数。调用方按题决定结构化 prompt 用哪条
    # 表格规则（只有该题的表格**全部**有图才禁 Markdown 重抄，否则那张表的
    # HTML 被禁了、图又没有，题目会整块丢内容）。
    table_counts: dict[int, int] = field(default_factory=dict)


def paired_image_rects(
    image_rects: list,
    question_rect: fitz.Rect,
    min_size_pt: float = DEFAULT_MIN_SIZE_PT,
) -> list[tuple[fitz.Rect, fitz.Rect]]:
    """返回 (原图矩形, 与题目区域的交集)。

    归属判定必须按「原图矩形」去重 —— 交集矩形逐题不同，拿它当键会把同一张
    跨题图当成多张独立的图。
    """
    results: list[tuple[fitz.Rect, fitz.Rect]] = []
    for rect in image_rects:
        image_rect = fitz.Rect(rect)
        if image_rect.width < min_size_pt or image_rect.height < min_size_pt:
            continue
        intersection = image_rect & question_rect
        if intersection.is_empty or intersection.width <= 0 or intersection.height <= 0:
            continue
        results.append((image_rect, intersection))
    return results


def intersect_image_rects(
    image_rects: list,
    question_rect: fitz.Rect,
    min_size_pt: float = DEFAULT_MIN_SIZE_PT,
) -> list[fitz.Rect]:
    """求图片矩形与题目区域的交集；过小的装饰图按原图尺寸判定后剔除。"""
    return [clip for _image_rect, clip in paired_image_rects(image_rects, question_rect, min_size_pt)]


def dropped_by_size_rects(
    image_rects: list,
    question_rect: fitz.Rect,
    min_size_pt: float = FIGURE_MIN_SIZE_PT,
) -> list[fitz.Rect]:
    """与题目区域相交、却因尺寸小于阈值被当作装饰图丢弃的图片矩形。

    剔除本身是对的（项目符号、边框必须滤掉），但**不能没有痕迹**：
    阈值再怎么调，总会有真实插图落在它下面（手机、旋钮这类窄高实拍图）。
    静默丢弃的表现是"这道题少了一张图、而且没有任何提示"，复核老师无从发现。
    所以把它们报出来，由上层写进告警，让人工能核对。
    """
    results: list[fitz.Rect] = []
    for rect in image_rects:
        image_rect = fitz.Rect(rect)
        if image_rect.width >= min_size_pt and image_rect.height >= min_size_pt:
            continue
        intersection = image_rect & question_rect
        if intersection.is_empty or intersection.width <= 0 or intersection.height <= 0:
            continue
        results.append(image_rect)
    return results


def is_blank_image(image: Image.Image) -> bool:
    """近纯色或过小的裁切结果没有信息量，不该作为插图入库。"""
    if min(image.size) < MIN_RENDERED_PX:
        return True
    low, high = image.convert("L").getextrema()
    return (high - low) < BLANK_GRAY_RANGE


def recurring_xrefs(
    doc: fitz.Document,
    min_pages: int = RECURRING_PAGE_MIN,
) -> set[int]:
    """跨页复现的图片对象：页眉/页脚/水印/logo，一律不作为题目插图。"""
    seen: dict[int, set[int]] = {}
    for page_index in range(doc.page_count):
        for image_info in doc[page_index].get_images(full=True):
            seen.setdefault(image_info[0], set()).add(page_index)
    return {xref for xref, pages in seen.items() if len(pages) >= min_pages}


class FigureExtractor:
    """把题目区域内嵌位图按高清 DPI 裁出，独立保存到 figures/ 目录。

    矢量绘制图（常见电路图）不在 get_images 结果内，随题卡整图保留，不单独拆分。

    归属是全局排定的：一张图只归交集面积最大的那一道题。逐题独立判定会让同一
    张图进多道题的 figure_paths —— 一张跨题示意图只要与多个题目矩形都有交集
    （题间共享的图、跨页拼接题、被当作底图的整页水印）就会重复出现。实测和平卷
    第 3~6 题都挂上了同一张运动示意图，导出后每题都带着别人的图。

    判归属看**交集面积**，落盘裁的却是**整张图** —— 两者刻意不一致：
    交集只回答"这张图更像谁的"，拿它当裁切框则会在图压住题目边界时裁出一条缝。
    """

    def __init__(
        self,
        dpi: int = 300,
        webp_quality: int = 92,
        min_size_pt: float = FIGURE_MIN_SIZE_PT,
    ):
        self.min_size_pt = min_size_pt
        # 复用题卡的渲染与白边收紧逻辑，保证插图与题卡视觉一致。
        self._cropper = QuestionCropper(dpi=dpi, webp_quality=webp_quality)
        # 最近一次 extract_all 的丢弃统计，供上层写进告警。
        self.last_blank_dropped = 0
        self.last_shared_reassigned = 0
        self.last_recurring_dropped = 0
        # 题号 -> 因尺寸偏小被丢弃的插图张数（去重后）。供上层逐题告警。
        self.last_size_dropped: dict[int, int] = {}
        # 题号 -> 重合比例过低（可能是章节横幅，也可能是跨页续页的图）的插图张数。
        # 这些图**照常收下**，只是要提醒人工看一眼。
        self.last_low_overlap: dict[int, int] = {}
        # 题号 -> [(xref, 裁出的文件名)]，顺序与 figures 列表一致。答案区抽图要
        # 用它判断「答案区那张图是不是题干图的重印」——同一 xref 即同一图对象。
        self.last_xref_figure_pairs: dict[int, list[tuple[int, str]]] = {}

    def extract_all(
        self,
        doc: fitz.Document,
        records: list[QuestionRecord],
        figures_dir: Path,
    ) -> dict[int, list[str]]:
        figures_dir.mkdir(parents=True, exist_ok=True)
        plans = self.plan_ownership_with_xrefs(
            doc, records, recurring=recurring_xrefs(doc)
        )
        results: dict[int, list[str]] = {}
        self.last_xref_figure_pairs = {}
        dropped = 0
        for record in records:
            paths: list[str] = []
            pairs: list[tuple[int, str]] = []
            index = 0
            for page_index, clip, xref in plans.get(record.number, []):
                image = self._cropper._render_segment(doc[page_index], clip)
                if is_blank_image(image):
                    dropped += 1
                    continue
                index += 1
                name = f"Q{record.number:03d}_{index:02d}.webp"
                save_webp(image, figures_dir / name, self._cropper.webp_quality)
                paths.append(f"figures/{name}")
                pairs.append((xref, f"figures/{name}"))
            results[record.number] = paths
            self.last_xref_figure_pairs[record.number] = pairs
        self.last_blank_dropped = dropped
        return results

    def _plan_ownership(
        self,
        doc: fitz.Document,
        records: list[QuestionRecord],
        recurring: set[int] = frozenset(),  # type: ignore[assignment]
    ) -> dict[int, list[tuple[int, fitz.Rect]]]:
        """排定「哪张图归哪道题」，返回 题号 -> [(页序, 整张图的矩形)]（已排序）。"""
        detailed = self.plan_ownership_with_xrefs(doc, records, recurring)
        return {
            number: [(page_index, clip) for page_index, clip, _xref in entries]
            for number, entries in detailed.items()
        }

    def plan_ownership_with_xrefs(
        self,
        doc: fitz.Document,
        records: list[QuestionRecord],
        recurring: set[int] = frozenset(),  # type: ignore[assignment]
    ) -> dict[int, list[tuple[int, fitz.Rect, int]]]:
        """同 `_plan_ownership`，但把图对象的 xref 一并带出来。

        答案区抽图必须能判断「答案区里的那张图是不是题干图的重印」——最硬的判据
        就是同一个图对象被两处引用（xref 相同）。两侧的归属口径必须完全一致，
        否则会把本该保留的答案图误判成重印而丢掉，所以这里复用同一套排定逻辑，
        只是多返回一个 xref，不做任何第二套判断。
        """
        # key: (页序, xref, 原图矩形) -> [(交集面积, 题号, 页序, 裁切矩形)]
        claims: dict[tuple, list[tuple[float, int, int, fitz.Rect]]] = {}
        skipped: set[int] = set()
        size_dropped: dict[int, set[tuple]] = {}
        for record in records:
            for segment in record.segments:
                page_index = segment.page_index
                page = doc[page_index]
                question_rect = fitz.Rect(segment.x0, segment.y0, segment.x1, segment.y1)
                for image_info in page.get_images(full=True):
                    xref = image_info[0]
                    if xref in recurring:
                        skipped.add(xref)
                        continue
                    try:
                        image_rects = page.get_image_rects(xref)
                    except Exception:
                        # 个别被遮罩或损坏的图片对象无法取矩形，跳过不影响其余内容。
                        continue
                    for image_rect, clip in paired_image_rects(
                        image_rects, question_rect, self.min_size_pt
                    ):
                        key = (
                            page_index,
                            xref,
                            round(image_rect.x0, 1),
                            round(image_rect.y0, 1),
                            round(image_rect.x1, 1),
                            round(image_rect.y1, 1),
                        )
                        # 存**整张图的矩形**，只把交集面积留给归属仲裁用。
                        # 曾经这里存的是交集，于是图压在题目边界上时（密集讲义里很常见）
                        # 裁出来只有一条缝：实测南开卷讲义第 55 题原图 117x52pt 只裁到
                        # 117x20pt（38%），落盘就是半截弧线 —— 复核时看着像"不相干的图片"。
                        # 答案区抽图早就为此取整张图（见 answer_figures 的同名注释），
                        # 正文抽图这条路径当时没跟上。
                        claims.setdefault(key, []).append(
                            (clip.get_area(), record.number, page_index, image_rect)
                        )

                    # 与题目区域相交却因尺寸被剔除的图：按 (页, xref, 矩形) 去重后
                    # 记到该题名下。同一张碎片图可能压到多道题，去重才不会重复告警。
                    for image_rect in dropped_by_size_rects(
                        image_rects, question_rect, self.min_size_pt
                    ):
                        size_dropped.setdefault(record.number, set()).add(
                            (
                                page_index,
                                xref,
                                round(image_rect.x0, 1),
                                round(image_rect.y0, 1),
                                round(image_rect.x1, 1),
                                round(image_rect.y1, 1),
                            )
                        )
        self.last_recurring_dropped = len(skipped)
        self.last_size_dropped = {
            number: len(rects) for number, rects in size_dropped.items()
        }

        plans: dict[int, list[tuple[int, fitz.Rect, int]]] = {}
        low_overlap: dict[int, set[tuple]] = {}
        shared = 0
        for key, candidates in claims.items():
            if len({candidate[1] for candidate in candidates}) > 1:
                shared += 1
            # 交集面积最大者胜出；面积相同归题号靠前的，保证结果可复现。
            # 注意：判归属用交集面积，但**裁切用整张图**（candidates 里存的就是整张图矩形）。
            _area, number, page_index, image_rect = min(
                candidates, key=lambda candidate: (-candidate[0], candidate[1])
            )
            # 仲裁之后记一笔重合比例：胜出的题也只压住图的一小角时，这张图可疑
            # （章节横幅？跨页续页的图？），**但照收不误**，只留给人工核对。
            # 界线与"为什么不当过滤器"见 LOW_OVERLAP_WARN_RATIO 的注释。
            if _area / max(image_rect.get_area(), 1e-6) < LOW_OVERLAP_WARN_RATIO:
                low_overlap.setdefault(number, set()).add(key)
            plans.setdefault(number, []).append((page_index, image_rect, key[1]))
        self.last_shared_reassigned = shared
        self.last_low_overlap = {
            number: len(keys) for number, keys in low_overlap.items()
        }

        for number, entries in plans.items():
            # 与 MinerU 路径同一口径：阅读顺序（行→列），见 sort_reading_order。
            plans[number] = sort_reading_order(entries)
        return plans


def extract_candidate_figures(
    records: list[QuestionRecord],
    candidates: list[FigureCandidate],
    figures_dir: Path,
    *,
    quality: int = 92,
) -> CandidateFigureResult:
    """把外部插图候选（MinerU 的 image 块）按题目归属落盘。

    与 `FigureExtractor.extract_all` 的差别只有一处：**图从哪来**。
    这里不去页面上找内嵌位图，直接用调用方给的矩形与图片文件；归属仲裁
    （交集面积最大者胜出、面积相同归题号靠前）与落盘命名（Q0NN_ii.webp）
    完全沿用同一套口径，所以下游的资产解析、导出、复核页一行都不用改。
    """
    figures_dir.mkdir(parents=True, exist_ok=True)
    result = CandidateFigureResult()

    # 候选下标 -> [(交集面积, 题号)]。同一道题在一页上可能有多个片段
    # （跨页题），取面积最大的那一段参与仲裁，避免同一对关系被记两次。
    ranked_by_candidate: dict[int, list[tuple[float, int]]] = {}
    for index, candidate in enumerate(candidates):
        rect = candidate.rect
        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
            continue
        best_per_record: dict[int, float] = {}
        for record in records:
            for segment in record.segments:
                if segment.page_index != candidate.page_index:
                    continue
                question_rect = fitz.Rect(segment.x0, segment.y0, segment.x1, segment.y1)
                intersection = rect & question_rect
                if intersection.is_empty or intersection.width <= 0 or intersection.height <= 0:
                    continue
                area = intersection.get_area()
                if area > best_per_record.get(record.number, 0.0):
                    best_per_record[record.number] = area
        if best_per_record:
            ranked_by_candidate[index] = sorted(
                ((area, number) for number, area in best_per_record.items()),
                key=lambda item: (-item[0], item[1]),
            )

    plans: dict[int, list[FigureCandidate]] = {}
    for index, ranked in ranked_by_candidate.items():
        area, number = ranked[0]
        candidate = candidates[index]
        if area / max(candidate.rect.get_area(), 1e-6) < LOW_OVERLAP_WARN_RATIO:
            result.low_overlap[number] = result.low_overlap.get(number, 0) + 1
        plans.setdefault(number, []).append(candidate)

    for record in records:
        # 阅读顺序（先分行、行内按 x），不是 (page, y0, x0) 字典序 ——
        # 并排图块的 y0 常常只差几个点，字典序会把左右顺序打乱，理由见 sort_reading_order。
        #
        # **必须解出 payload**：sort_reading_order 返回的是它收到的那些
        # (page, rect, payload) 元组。直接把元组当 FigureCandidate 用，会在
        # candidate.path 上抛 AttributeError，被下面的 except 吞成 unreadable ——
        # 结果是整题的插图全丢，界面上只留一句"N 张读取失败"。这条踩过一次。
        ordered = sort_reading_order([
            (candidate.page_index, candidate.rect, candidate)
            for candidate in plans.get(record.number, [])
        ])
        paths: list[str] = []
        table_count = 0
        for _page, _rect, candidate in ordered:
            try:
                image = Image.open(candidate.path).convert("RGB")
            except Exception:  # noqa: BLE001 — 单张读不出来不该中断整批
                result.unreadable += 1
                continue
            if is_blank_image(image):
                result.unreadable += 1
                continue
            name = f"Q{record.number:03d}_{len(paths) + 1:02d}.webp"
            save_webp(image, figures_dir / name, quality)
            paths.append(f"figures/{name}")
            if candidate.kind == "table":
                table_count += 1
        result.figures[record.number] = paths
        if table_count:
            result.table_counts[record.number] = table_count
    return result
