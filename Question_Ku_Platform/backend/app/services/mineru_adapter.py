"""content_list.json → TextLine 行清单（MinerU 通道的适配层 / 翻译官）。

定位与 api_extract_adapter 相同：这是 MinerU 通道里**唯一**了解 content_list
内部结构的模块。上游（步骤 2 的 mineru_service）只拿到 list[TextLine]，
它与本地 PyMuPDF 通道产出的清单完全同构，因此
boundary / structure / answers / audit / QuestionCropper 全部零改动复用。

四条实测结论决定了这里的写法（证据见 data/_probe_mineru/<卷>/<后端>/mineru_probe_report.md）：
1. bbox 是 0~1000 的**按轴归一化**值，不是 PDF 点。用 PyMuPDF 的 search_for
   做交叉验证：15 个样本平均偏差 3.9pt；若按点理解，偏差 129pt。
   vlm 与 pipeline 两个后端结论一致，所以**不需要**按 model_version 分支。
2. 噪声块有独立的 type（header / footer / page_number，实测 152/695），
   按 type 直接丢弃即可 —— 比本地通道 detect_running_lines 的「统计重复行」
   启发式可靠得多，而且零成本。
3. text 块基本是行级（429 个里只有 20 个含换行，中位 44 字），映射近乎 1:1。
4. 题注/脚注字段（image_caption 等）里**混着题干文字**：实测 23 条题注中
   1 条是 MinerU 占位符、22 条是真实内容，其中 4 条（2 句话各出现 2 次）
   在正文里**完全找不到** —— 丢掉就是漏题。所以题注要纳入清单
   （借所属块的 bbox 定位），并滤掉 "[Figure]" 这类占位符。

刻意**不做**的两件事：
- 不重排 line_id。本地通道的 _renumber 按 (页, y, x) 排序，双栏排版下会把左右栏
  交错；MinerU 的 content_list 本身就是版面感知的阅读顺序，严格更好。
  代价：必须自己保证 line_id 单调递增（见 build_lines 末尾）。
- 不把 text_level 写进行文本。to_plain_text 的注释记着教训 —— 把
  「#539 [p14 y=...]」这类前缀混进正文，模型会把前缀当题号吐出来。
  章节标题由边界判定的 LLM 自己归类为 section_header，不需要我们提示。
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import pymupdf as fitz

# 与 api_extract_adapter 同样的手法：把 packages/ 挂进 sys.path，
# 以便直接 import physics_paper_splitter（该包源码不改）。
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from physics_paper_splitter.figures import FigureCandidate  # noqa: E402
from physics_paper_splitter.lines import TextLine  # noqa: E402

logger = logging.getLogger(__name__)

# 行列归一化空间：bbox 的上界（0~1000）。
BBOX_SCALE = 1000.0

# 页眉 / 页脚 / 页码：MinerU 已按 type 标好，直接丢。
NOISE_TYPES = frozenset({"header", "footer", "page_number"})

# 这些 type 没有正文文本（正文在 img_path 指向的图里）。
# 注意：它们**不产出 TextLine**，但题卡裁剪用的是「题目所有行的 y 区间」，
# 夹在文字行之间的插图本来就会被框进题卡；插图归题另有 FigureExtractor 负责。
NON_TEXT_TYPES = frozenset({"image", "chart"})

# 已知的有正文的 type。其它带正文的类型视为 MinerU 新增类型，按正文纳入并告警。
KNOWN_BODY_TYPES = frozenset({"text", "equation", "table"})

# 可以当插图用的块类型：三者 MinerU 都会按版面渲染成图片（img_path），且都没有正文。
#
# table 为什么也要算（这就是「表格只有一半」的修法）：table_body 是 HTML（含
# colspan/rowspan），而 Markdown 表达不了合并单元格。实测 2026 河东一模第 24 题，
# 原件 7 行 16 格、rowspan×2，模型把它转成 Markdown 后合并关系全丢 ——
# `<td rowspan="3">方案一</td>` 变成 `| 方案一 |  |`，方案一/方案二的分组消失，
# 界面上就成了"表格只有一半"。MinerU 的渲染图是完整的（合并、空格线都在），
# 所以与其让模型抄一半，不如直接把整张表当插图送进去。
#
# chart 之前两头都漏：既不在 NON_TEXT_TYPES 里产行（它本来就没正文），也不在这里
# 产图，于是整块从流水线消失。
FIGURE_BLOCK_TYPES = frozenset({"image", "chart", "table"})

# MinerU 自己的图片占位符，实测会出现在 image_footnote 里（"[Figure]"）。
# 它不是文档内容，混进行清单只会干扰边界判定的模型。
PLACEHOLDER_CAPTIONS = frozenset(
    {"[figure]", "[table]", "[chart]", "[image]", "[equation]"}
)

# 只有 text 块按换行拆成多个逻辑行（实测 20/429 个 text 块是多行段落）。
# equation 的正文形如 "$$\n公式\n$$"、table 的正文是一整段 HTML ——
# 对它们按换行拆，会让 "$$" 单独占一行，直接把 LaTeX 弄坏（自检抓到过这一条）。
SPLITTABLE_TYPES = frozenset({"text"})

# 题注 / 脚注类字段。它们**没有独立坐标**（content_list 只给了文本），
# 塞进行清单只能借用所属块的 bbox，位置必然是错的，所以这里不纳入，
# 只统计非空数量并告警 —— 让内容缺失可见，而不是悄悄丢。
# 实测本卷有 18 个 image/table/chart 块的题注或脚注非空。
CAPTION_FIELDS = (
    "image_caption",
    "image_footnote",
    "chart_caption",
    "chart_footnote",
    "table_caption",
    "table_footnote",
)


@dataclass(slots=True)
class LineInventory:
    """翻译结果：可直接喂给 detect_boundaries 的行清单 + 诊断信息。"""

    lines: list[TextLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# ── content_list 读取 ────────────────────────────────────────────────


def load_blocks(path: Path | str) -> list[dict]:
    """读 content_list，兼容两种容器形态：

    - v1（`*_content_list.json`）：list[dict]，block 自带 page_idx；
    - v2（`*_content_list_v2.json`）：list[list[dict]]，外层下标即页序。

    实测一卷里两个文件同时存在（v1 207KB / v2 433KB），v2 的 block 只有
    type/content/bbox 三个键、正文藏在 content 里，结构更绕。选 v1。
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    if raw and isinstance(raw[0], list):
        blocks: list[dict] = []
        for page_index, group in enumerate(raw):
            for block in group or []:
                if isinstance(block, dict):
                    # __page 只做兜底，block 自带 page_idx 时以后者为准（见 block_page）。
                    blocks.append({"__page": page_index, **block})
        return blocks
    return [block for block in raw if isinstance(block, dict)]


def block_page(block: dict) -> int | None:
    """block 所在页（0 基）。v2 靠外层下标，v1 靠 page_idx。"""
    for key in ("page_idx", "__page", "page"):
        value = block.get(key)
        if isinstance(value, int):
            return value
    return None


def block_bbox(block: dict) -> list[float] | None:
    """取 bbox=[x0,y0,x1,y1]（归一化 0~1000）。实测 695/695 个块都有。"""
    bbox = block.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None


def _block_body(block: dict) -> str:
    """一个块的正文文本。

    table 的正文在 table_body（HTML，含 colspan/rowspan）；其余在 text。
    这里**不做 HTML→Markdown 转换**：colspan/rowspan 转成 Markdown 一定丢信息，
    而 structure prompt 本来就要求模型「原样保留表格行列结构」，
    直接把 HTML 交给它比我先做一次有损转换更忠实。
    """
    if str(block.get("type") or "") == "table":
        return str(block.get("table_body") or "").strip()
    return str(block.get("text") or "").strip()


def _has_caption(block: dict) -> bool:
    return any(block.get(field) for field in CAPTION_FIELDS)


def _caption_texts(block: dict) -> list[str]:
    """收集块上的题注与脚注文本。

    这些文本**真的夹着题干**：实测 23 条题注里 4 条是正文中完全找不到的题干
    （"（2）请你画出对应的电路图；"、"（3）电路改正后，小明得到的实验数据如表所示。"），
    丢掉就是漏题；其余多是图注（"图1"、"甲"、"乙"）。它们没有独立坐标，
    位置只能借用所属块的 bbox。
    """
    texts: list[str] = []
    for field in CAPTION_FIELDS:
        values = block.get(field)
        if not isinstance(values, list):
            continue
        for item in values:
            text = " ".join(str(item).split())
            if text:
                texts.append(text)
    return texts


def _norm(text: str) -> str:
    """去空白后比较：同一句话在正文与题注里的空白习惯不一致。"""
    return "".join(text.split())


def _make_line(
    page_index: int, y0: float, y1: float, x0: float, x1: float, text: str
) -> TextLine:
    """line_id 由 build_lines 统一分配，这里一律先填 -1。"""
    return TextLine(
        line_id=-1, page_index=page_index, y0=y0, y1=y1, x0=x0, x1=x1, text=text
    )


# ── 归一化坐标 → PDF 点 ──────────────────────────────────────────────


def page_sizes_from_pdf(pdf_path: Path | str) -> dict[int, tuple[float, float]]:
    """取原 PDF 每页尺寸：page_index -> (页宽pt, 页高pt)。

    必须用**原 PDF**，不能用 MinerU 回寄的 `*_origin.pdf`：后者可能被重排或
    换尺寸，页码与我们的裁剪目标就不再一一对应。
    放在这里是因为生产与脚本两侧都要用，各自复制一份迟早会漂移。
    """
    with fitz.open(str(pdf_path)) as doc:
        return {
            index: (float(page.rect.width), float(page.rect.height))
            for index, page in enumerate(doc)
        }


def _to_points(
    bbox: list[float], width: float, height: float
) -> tuple[float, float, float, float]:
    """把 0~1000 的按轴归一化 bbox 换成 PDF 点 (x0, y0, x1, y1)。

    退化保护与本项目其它地方一致（boundary.transcribe_page）：
    宽或高为 0 时给 1pt，避免下游出现零面积区间。
    """
    x0 = bbox[0] / BBOX_SCALE * width
    x1 = bbox[2] / BBOX_SCALE * width
    y0 = bbox[1] / BBOX_SCALE * height
    y1 = bbox[3] / BBOX_SCALE * height
    if x1 <= x0:
        x1 = x0 + 1.0
    if y1 <= y0:
        y1 = y0 + 1.0
    return round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)


def _split_block(
    body: str,
    bbox: list[float],
    width: float,
    height: float,
    *,
    allow_split: bool,
) -> list[tuple[str, float, float, float, float]]:
    """把一个块的正文变成若干逻辑行，返回 (文本, y0, y1, x0, x1)。

    为什么要拆：to_prompt_text 的格式是**一行一个 line_id**，块文本里夹换行会
    把这个格式弄坏，边界判定的模型会数错行。

    拆法是把块的高度按行数均分。**外层包络严格不变**（首行 y0 = 块 y0，
    末行 y1 = 块 y1），所以裁题卡用的区间与块完全一致；只有块内部的中间行
    位置是近似的 —— 中间行只影响模型数行的粒度，不影响裁剪结果。

    allow_split=False（equation / table / 未知类型）时只折叠空白、保持单行：
    公式与表格是**一个整体**，拆开就毁了，它们的换行不是版面换行。
    """
    x0, y0, x1, y1 = _to_points(bbox, width, height)
    if not allow_split:
        collapsed = " ".join(body.split())
        return [(collapsed, y0, y1, x0, x1)] if collapsed else []

    parts = [line.strip() for line in body.splitlines() if line.strip()]
    if not parts:
        return []
    if len(parts) == 1:
        # 单行块：仍要把内部残留的空白折叠掉，保证是一个逻辑行。
        return [(" ".join(parts[0].split()), y0, y1, x0, x1)]

    step = (y1 - y0) / len(parts)
    return [
        (part, round(y0 + index * step, 2), round(y0 + (index + 1) * step, 2), x0, x1)
        for index, part in enumerate(parts)
    ]


# ── 插图候选 ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class FigureInventory:
    """插图候选：可直接喂给 run_extract 的 figures_override + 诊断信息。"""

    candidates: list[FigureCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def build_figure_candidates(
    content_list_path: Path | str,
    *,
    page_sizes: Mapping[int, tuple[float, float]],
    images_root: Path | str,
) -> FigureInventory:
    """把 content_list 里的 image / chart / table 块变成插图候选。

    为什么值得单独做一条路：本地那套 FigureExtractor 只认页面上的**内嵌位图**，
    而讲义/学案这类 Word 导出件里的插图多是**矢量线条画**（容器、电路、光路），
    一张都拿不到 —— 实测某讲义 75 题只抽到 36 张，MinerU 这边 79 张且包含
    那些矢量图。MinerU 是"按版面切区域再渲染"，所以它的图天然覆盖矢量内容。

    表格也走这条路（见 FIGURE_BLOCK_TYPES），因为 Markdown 抄不下合并单元格。

    bbox 是 0~1000 归一化坐标，换算口径与行清单完全一致（见模块 docstring）。
    """
    images_root = Path(images_root)
    inventory = FigureInventory()
    by_type: Counter = Counter()
    no_bbox = 0
    bad_page = 0
    missing_file = 0
    tables_total = 0
    tables_usable = 0

    for block in load_blocks(content_list_path):
        block_type = str(block.get("type") or "")
        by_type[block_type] += 1
        if block_type not in FIGURE_BLOCK_TYPES:
            continue
        if block_type == "table":
            tables_total += 1
        img_path = block.get("img_path")
        bbox = block_bbox(block)
        page_index = block_page(block)
        if not isinstance(img_path, str) or not img_path or bbox is None:
            # 没有 img_path / bbox 的 image 块无从下手（实测都会给），记数不静默。
            no_bbox += 1
            continue
        if page_index is None or page_index not in page_sizes:
            bad_page += 1
            continue
        width, height = page_sizes[page_index]
        x0, y0, x1, y1 = _to_points(bbox, width, height)
        path = images_root / img_path
        if not path.is_file():
            missing_file += 1
            continue
        inventory.candidates.append(
            FigureCandidate(page_index, x0, y0, x1, y1, path, kind=block_type)
        )
        if block_type == "table":
            tables_usable += 1

    inventory.stats = {
        "blocks_total": sum(by_type.values()),
        "by_type": dict(by_type),
        "candidates": len(inventory.candidates),
        # 调用方要靠这两个数决定结构化 prompt 用哪条表格规则（见 prompts.py）。
        "tables_total": tables_total,
        "tables_usable": tables_usable,
    }
    skipped = no_bbox + bad_page + missing_file
    if inventory.candidates:
        inventory.warnings.append(
            f"MinerU 按版面提供 {len(inventory.candidates)} 张插图候选"
            f"（含矢量图与表格/图表渲染图 —— 本地内嵌位图抽取拿不到这类）"
        )
    if tables_total > tables_usable:
        inventory.warnings.append(
            f"有 {tables_total - tables_usable} 个表格块没拿到渲染图，"
            f"该表格只能靠正文里的 HTML 还原，合并单元格可能丢失，请复核。"
        )
    if skipped:
        inventory.warnings.append(
            f"有 {skipped} 个 MinerU 图片块被跳过"
            f"（缺 img_path/bbox {no_bbox}、页码越界 {bad_page}、文件缺失 {missing_file}）"
        )
    return inventory


# ── 主入口 ───────────────────────────────────────────────────────────


def build_lines(
    content_list_path: Path | str,
    *,
    page_sizes: Mapping[int, tuple[float, float]],
) -> LineInventory:
    """把 content_list.json 翻译成行清单。

    Args:
        content_list_path: `*_content_list.json` 的路径。
        page_sizes: page_index -> (页宽pt, 页高pt)，来自**原 PDF** 的 PyMuPDF
            page.rect。归一化坐标离了页尺寸就没有绝对值，所以这是必需输入；
            用原 PDF 而不是 MinerU 回寄的 `*_origin.pdf`，保证页码一一对应。

    返回的 LineInventory.lines 已经是可直接喂给 detect_boundaries 的形态：
    line_id 全清单单调递增、y 是 PDF 点、页眉页脚页码已剔除。
    """
    blocks = load_blocks(content_list_path)
    lines: list[TextLine] = []
    warnings: list[str] = []
    by_type: Counter = Counter()
    noise_dropped = 0
    non_text_dropped = 0
    missing_bbox = 0
    empty_body = 0
    out_of_range: list[int] = []
    caption_blocks = 0
    caption_dups = 0
    caption_placeholders = 0
    caption_unplaced = 0
    unknown_types: Counter = Counter()
    last_page = -1
    non_monotonic = 0
    # (是否来自题注, 行)。题注要参与「与正文去重」，所以先攒着，最后统一编号。
    pending: list[tuple[bool, TextLine]] = []

    for block in blocks:
        block_type = str(block.get("type") or "(无 type)")
        by_type[block_type] += 1

        if block_type in NOISE_TYPES:
            noise_dropped += 1
            continue

        page_index = block_page(block)
        if page_index is None or page_index not in page_sizes:
            if page_index is not None:
                out_of_range.append(page_index)
            continue
        if page_index < last_page:
            non_monotonic += 1
        last_page = page_index

        bbox = block_bbox(block)
        width, height = page_sizes[page_index]

        # ① 正文
        body = "" if block_type in NON_TEXT_TYPES else _block_body(block)
        if body:
            if bbox is None:
                # 没有 bbox 就无法定位，只能丢；必须让它在告警里出现。
                missing_bbox += 1
            else:
                if block_type not in KNOWN_BODY_TYPES:
                    unknown_types[block_type] += 1
                for text, y0, y1, x0, x1 in _split_block(
                    body,
                    bbox,
                    width,
                    height,
                    allow_split=block_type in SPLITTABLE_TYPES,
                ):
                    pending.append((False, _make_line(page_index, y0, y1, x0, x1, text)))
        elif block_type in NON_TEXT_TYPES:
            non_text_dropped += 1
        else:
            empty_body += 1

        # ② 题注 / 脚注（正文在图里、题注里反而有题干文字）
        caption_texts = _caption_texts(block)
        if not caption_texts:
            continue
        caption_blocks += 1
        if bbox is None:
            caption_unplaced += len(caption_texts)
            continue
        placeable = [
            text for text in caption_texts if _norm(text).lower() not in PLACEHOLDER_CAPTIONS
        ]
        caption_placeholders += len(caption_texts) - len(placeable)
        for text, y0, y1, x0, x1 in _split_block(
            "\n".join(placeable), bbox, width, height, allow_split=True
        ):
            pending.append((True, _make_line(page_index, y0, y1, x0, x1, text)))

    # 题注去重是**防御性**的：实测本卷一条精确重复都没有 —— 那 18 条"重复"
    # 是子串匹配造出来的误报（"图1"恰好出现在"如图1所示"这类正文里），
    # 所以这里只做精确比较（去空白后全等），绝不改回子串匹配：
    # 子串匹配会把"图1"这种图注当成重复丢掉，正好丢掉真实内容。
    body_texts = {_norm(line.text) for is_caption, line in pending if not is_caption}
    lines: list[TextLine] = []
    for is_caption, line in pending:
        if is_caption and _norm(line.text) in body_texts:
            caption_dups += 1
            continue
        lines.append(line)
    caption_added = sum(1 for is_caption, _ in pending if is_caption) - caption_dups

    # 按 content_list 的原顺序编号，不做 (页, y, x) 重排 —— 理由见模块 docstring。
    for order, line in enumerate(lines, start=1):
        line.line_id = order

    stats = {
        "blocks_total": len(blocks),
        "lines_total": len(lines),
        "noise_dropped": noise_dropped,
        "non_text_dropped": non_text_dropped,
        "caption_blocks": caption_blocks,
        "caption_added": caption_added,
        "caption_dups": caption_dups,
        "by_type": dict(by_type),
    }

    if not lines:
        warnings.append("content_list 里没有翻译出任何文字行，该文档无法切题。")
    if noise_dropped:
        logger.info("mineru_adapter 剔除页眉/页脚/页码 %d 块", noise_dropped)
    if non_monotonic:
        warnings.append(
            f"content_list 里有 {non_monotonic} 处页码倒序，行清单顺序可能与版面顺序不符。"
        )
    if out_of_range:
        warnings.append(
            f"有 {len(out_of_range)} 个块的页码超出 PDF 页数"
            f"（最大 page_idx={max(out_of_range)}），已丢弃。"
        )
    if missing_bbox:
        warnings.append(f"有 {missing_bbox} 个块没有 bbox，无法定位，已丢弃。")
    if caption_blocks:
        detail = (
            f"题注并入行清单：{caption_blocks} 个图片/表格块带题注或脚注，"
            f"补充 {caption_added} 行、跳过 {caption_dups} 行与正文重复的、"
            f"{caption_placeholders} 行为 MinerU 占位符"
        )
        if caption_unplaced:
            detail += f"，另有 {caption_unplaced} 行因缺 bbox 无法定位"
        # 措辞里带上「行清单」是刻意的：这是管线内部处理细节（题注没有独立坐标，
        # 位置借用所属块的 bbox），归入开发者诊断，不必占用复核老师的警告条。
        warnings.append(detail + "；位置借用所属块的 bbox，可能有偏差。")
    if unknown_types:
        detail = "、".join(f"{name}×{count}" for name, count in unknown_types.most_common())
        warnings.append(f"出现未识别的 block 类型（已按正文纳入行清单）：{detail}")

    # 整页无行 = 孤儿页，覆盖率审计会因此阻断整份文档，提前告警比事后排查便宜。
    pages_with_lines = {line.page_index for line in lines}
    empty_pages = sorted(set(page_sizes) - pages_with_lines)
    if empty_pages:
        warnings.append(
            f"有 {len(empty_pages)} 页没有任何文字行（第 "
            f"{[page + 1 for page in empty_pages[:20]]} 页），"
            f"它们会被覆盖率审计记为孤儿页。"
        )

    if empty_body:
        logger.info("mineru_adapter 跳过 %d 个正文为空的块", empty_body)

    return LineInventory(lines=lines, warnings=warnings, stats=stats)


def lines_to_text(lines: list[TextLine]) -> str:
    """行清单的可读快照，用于探针/排查时人工核对（不是生产路径）。"""
    return "\n".join(
        f"#{line.line_id} p{line.page_index + 1} "
        f"y={line.y0:.1f}~{line.y1:.1f} x={line.x0:.1f}~{line.x1:.1f} | {line.text}"
        for line in lines
    )
