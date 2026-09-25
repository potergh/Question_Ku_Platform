"""统一渲染适配层（IR）—— F07 Task 7.8。

**问题**：此前 PDF 链路（`render_service` → `doc_render.question_html`）与
Word 链路（`docx_export._add_question_from_doc`）各自解析 `rich_document`，
"题号并入首个段落 / 连续图片并排 / 纯图题题号置顶 / 段落属性归一化" 等结构
判断在两边各写一遍，导致同类内容在 PDF 与 Word 里长期不一致（题号位置、
加粗残留、asset 引用是否内联）。

**做法**：单题富文本文档与整册内容块都先转成同一套中间结构（IR），
HTML（预览/PDF）与 Word 两个渲染器只做"IR → 目标格式"的投影，
结构判断全部集中在本模块。

**边界（明确不做）**：整册 `custom_text` 块的 HTML 是用户自撰富文本，
其 HTML→Word 转换属**格式桥接**（同 `_picture_source` 的 webp→PNG），
不属"题目结构推断"，故仍由 `CustomHtml` 块承载原文、Word 侧单独解析。
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services import practice_service, typography, workbook_layout

# fit 默认上限：宽不超内容区 50%、高不超 8cm（HTML 与 Word 同源）
FIT_STYLE = "max-width:50%;max-height:8cm"

# ── 行内节点 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Marks:
    """行内格式；各渲染器自行投影（HTML → 标签/内联样式，Word → run 属性）。"""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    superscript: bool = False
    subscript: bool = False
    font_family: str | None = None
    font_size: float | None = None
    color: str | None = None

    def merged(self, **kwargs) -> "Marks":
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data.update({k: v for k, v in kwargs.items() if v})
        return Marks(**data)


NO_MARKS = Marks()


@dataclass(frozen=True)
class Text:
    text: str
    marks: Marks = NO_MARKS


@dataclass(frozen=True)
class HardBreak:
    """软换行（段内换行）。"""


@dataclass(frozen=True)
class InlineImage:
    src: str


@dataclass(frozen=True)
class InlineFormula:
    latex: str
    display: bool = False


Inline = Text | HardBreak | InlineImage | InlineFormula


# ── 块节点 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Paragraph:
    runs: list[Inline] = field(default_factory=list)
    # 归一化后的段落属性；空 dict = 未定制（连续未定制段落由本模块合并为一段）
    style: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ImageBlock:
    src: str
    align: str = "center"
    width: str | float = "fit"
    layout: str = "row"   # row=可并排 / block=独占一行
    scale: float | None = None


@dataclass(frozen=True)
class ImageRow:
    """连续 row 图片并排一行。"""

    images: list[ImageBlock]


@dataclass(frozen=True)
class FormulaBlock:
    latex: str


@dataclass(frozen=True)
class OptionGroup:
    options: list[tuple[str, list[Inline]]]


@dataclass(frozen=True)
class AnswerSpace:
    rows: int


@dataclass(frozen=True)
class HorizontalRule:
    pass


@dataclass(frozen=True)
class ListBlock:
    ordered: bool
    items: list[list["Block"]]


@dataclass(frozen=True)
class Spacer:
    height_px: int


@dataclass(frozen=True)
class PageBreak:
    pass


@dataclass(frozen=True)
class Heading:
    level: str   # "title"（练习标题）/ "subtitle"（副标题）
    text: str


@dataclass(frozen=True)
class TotalScore:
    text: str


@dataclass(frozen=True)
class InfoBar:
    text: str
    align: str = "left"


@dataclass(frozen=True)
class SectionTitle:
    text: str   # 已含「一、」序号


@dataclass(frozen=True)
class CustomHtml:
    html: str
    align: str = "left"


@dataclass(frozen=True)
class QuestionGroup:
    """一道题的块集合。HTML 需要外层 `.question` 容器（间距由 CSS 控制），
    Word 无对应概念，直接顺序落段。"""

    blocks: list[Block]


Block = (Paragraph | ImageBlock | ImageRow | FormulaBlock | OptionGroup | AnswerSpace
         | HorizontalRule | ListBlock | Spacer | PageBreak | Heading | TotalScore
         | InfoBar | SectionTitle | CustomHtml | QuestionGroup)

INFO_BAR_TEXT = "姓名：____________　班级：____________　日期：____________"


# ── 段落属性归一化（原 doc_render.norm_para_attrs） ────────────────────

def norm_para_attrs(attrs) -> dict:
    """过滤等价默认值：ProseMirror 序列化会带上全部属性，未改过的不算局部覆盖。"""
    out = {}
    for k, v in (attrs or {}).items():
        if v is None or v is False or v == 0 or v == "":
            continue
        if k == "textAlign" and v == "left":
            continue
        out[k] = v
    return out


# ── 文本 → 行内 run（`**` 遗留加粗、`\n` 软换行、asset 引用内联图） ──────

_ASSET_RE = re.compile(r"!\[[^\]]*\]\((asset://[^\s\)]+)\)|(asset://[^\s\)]+)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def _text_runs(text: str, marks: Marks = NO_MARKS) -> list[Inline]:
    """文字 → run 序列。

    `**…**` 归一为 bold mark（此前 PDF 转 `<b>`、Word 直接删星号，行为不一致）；
    `\\n` 归一为 HardBreak（此前只有 Word/旧块路径换行）；asset 引用归一为内联图
    （此前只有 Word 与选项路径内联）。以上三点让两条链路从同一结构出发。
    """
    if not text:
        return []
    out: list[Inline] = []
    last = 0
    for m in _ASSET_RE.finditer(text):
        out.extend(_text_segments(text[last:m.start()], marks))
        out.append(InlineImage(src=(m.group(1) or m.group(2))))
        last = m.end()
    out.extend(_text_segments(text[last:], marks))
    return out


def _text_segments(text: str, marks: Marks) -> list[Inline]:
    """把 `**…**` 拆成 bold run；`\\n` 拆成 HardBreak。"""
    out: list[Inline] = []
    pos = 0
    for m in _BOLD_RE.finditer(text):
        out.extend(_plain_segments(text[pos:m.start()], marks))
        if marks.bold:
            out.extend(_plain_segments(m.group(1), marks))
        else:
            out.extend(_plain_segments(m.group(1), marks.merged(bold=True)))
        pos = m.end()
    out.extend(_plain_segments(text[pos:], marks))
    return out


def _plain_segments(text: str, marks: Marks) -> list[Inline]:
    out: list[Inline] = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append(HardBreak())
        if line:
            out.append(Text(line, marks))
    return out


# ── rich_document → Block ─────────────────────────────────────────────

_MARK_FLAGS = {"bold", "italic", "underline", "strike", "superscript", "subscript"}


def _marks_of(node: dict) -> Marks:
    m = NO_MARKS
    for mark in node.get("marks") or []:
        t = mark.get("type")
        if t in _MARK_FLAGS:
            m = m.merged(**{t: True})
        elif t == "textStyle":
            a = mark.get("attrs") or {}
            m = m.merged(
                font_family=a.get("fontFamily") or None,
                font_size=a.get("fontSize") if isinstance(a.get("fontSize"), (int, float)) else None,
                color=a.get("color") or None,
            )
    return m


def inline_runs(nodes) -> list[Inline]:
    """行内节点序列 → run 序列（rich_document 语法）。"""
    out: list[Inline] = []
    for n in nodes or []:
        t = n.get("type")
        attrs = n.get("attrs") or {}
        if t == "text":
            out.extend(_text_runs(n.get("text", ""), _marks_of(n)))
        elif t == "hardBreak":
            out.append(HardBreak())
        elif t == "inlineImage":
            out.append(InlineImage(src=attrs.get("src", "")))
        elif t == "inlineFormula":
            out.append(InlineFormula(latex=attrs.get("latex", "")))
        elif t == "displayFormula":
            out.append(InlineFormula(latex=attrs.get("latex", ""), display=True))
    return out


def _image_block(attrs: dict) -> ImageBlock:
    return ImageBlock(
        src=attrs.get("src", ""),
        align=attrs.get("align", "center"),
        width=attrs.get("width", "fit"),
        layout=attrs.get("layout", "row"),
        scale=attrs.get("scale") if isinstance(attrs.get("scale"), (int, float)) else None,
    )


def _list_block(node: dict) -> ListBlock:
    items: list[list[Block]] = []
    for item in node.get("content") or []:
        if item.get("type") != "listItem":
            continue
        blocks: list[Block] = []
        for inner in item.get("content") or []:
            if inner.get("type") == "paragraph":
                blocks.append(Paragraph(
                    runs=inline_runs(inner.get("content")),
                    style=norm_para_attrs(inner.get("attrs")),
                ))
            elif inner.get("type") in ("bulletList", "orderedList"):
                blocks.append(_list_block(inner))
        items.append(blocks)
    return ListBlock(ordered=node.get("type") == "orderedList", items=items)


def blocks_from_rich_doc(doc: dict) -> list[Block]:
    """单题富文本文档 → Block 序列（题号前缀由 `with_prefix` 统一并入）。"""
    out: list[Block] = []
    imgs: list[ImageBlock] = []
    pending: list[Inline] = []

    def flush_paras():
        if not pending:
            return
        out.append(Paragraph(runs=list(pending)))
        pending.clear()

    def flush_imgs():
        if not imgs:
            return
        if len(imgs) == 1:
            out.append(imgs[0])
        else:
            out.append(ImageRow(images=list(imgs)))
        imgs.clear()

    for node in doc.get("content") or []:
        t = node.get("type")
        attrs = node.get("attrs") or {}
        if t == "paragraph":
            style = norm_para_attrs(attrs)
            if not style:
                # 连续未定制段落合并为一段（段间软换行），与旧渲染粒度一致
                if pending:
                    pending.append(HardBreak())
                pending.extend(inline_runs(node.get("content")))
                continue
            flush_paras(); flush_imgs()
            out.append(Paragraph(runs=inline_runs(node.get("content")), style=style))
        elif t == "image":
            flush_paras()
            if attrs.get("layout") == "block":
                flush_imgs()
                out.append(_image_block(attrs))
            else:
                imgs.append(_image_block(attrs))
        elif t == "displayFormula":
            flush_paras(); flush_imgs()
            out.append(FormulaBlock(latex=attrs.get("latex", "")))
        elif t == "optionGroup":
            flush_paras(); flush_imgs()
            out.append(OptionGroup(options=[
                ((o.get("attrs") or {}).get("label", ""), inline_runs(o.get("content")))
                for o in node.get("content") or [] if o.get("type") == "option"
            ]))
        elif t == "answerSpace":
            flush_paras(); flush_imgs()
            out.append(AnswerSpace(rows=int(attrs.get("rows", 0))))
        elif t == "horizontalRule":
            flush_paras(); flush_imgs()
            out.append(HorizontalRule())
        elif t in ("bulletList", "orderedList"):
            flush_paras(); flush_imgs()
            out.append(_list_block(node))
    flush_paras(); flush_imgs()
    return out


# ── 旧内容块（PracticeContentBlock）→ Block（无富文档时的回退路径） ────

def blocks_from_legacy(blocks) -> list[Block]:
    out: list[Block] = []
    imgs: list[ImageBlock] = []

    def flush_imgs():
        if not imgs:
            return
        if len(imgs) == 1:
            out.append(imgs[0])
        else:
            out.append(ImageRow(images=list(imgs)))
        imgs.clear()

    for b in blocks:
        style = b.style_config or {}
        if b.block_type == "image":
            flush_imgs()
            imgs.append(ImageBlock(
                src=(b.content or ""), align=style.get("align", "center"),
                width=style.get("width", "fit"), layout="row",
            ))
            continue
        flush_imgs()
        if b.block_type == "text":
            out.append(Paragraph(runs=_text_runs(b.content or "")))
        elif b.block_type == "options":
            try:
                opts = json.loads(b.content) if b.content else []
            except (TypeError, json.JSONDecodeError):
                opts = []
            out.append(OptionGroup(options=[
                (o.get("label", ""), _text_runs(o.get("content", ""))) for o in opts
            ]))
        elif b.block_type == "answer_space":
            out.append(AnswerSpace(rows=int(style.get("rows", 0))))
        # answer/explanation 块学生版不输出（规格 11.2）
    flush_imgs()
    return out


def with_prefix(blocks: list[Block], prefix: str) -> list[Block]:
    """把「题号. （分值）」并入首个段落；无段落（纯图题）则在最前插入题号段。

    此前三条路径三种行为：富文档 HTML 置顶、富文档 Word 置尾（bug）、
    旧块 Word 置顶。此处统一为置顶。
    """
    if not prefix:
        return blocks
    head = Text(prefix, Marks(bold=True))
    for i, b in enumerate(blocks):
        if isinstance(b, Paragraph):
            blocks = list(blocks)
            blocks[i] = Paragraph(runs=[head, *b.runs], style=b.style)
            return blocks
    return [Paragraph(runs=[head]), *blocks]


# ── 整册内容块 → Block ────────────────────────────────────────────────

def custom_html_block(blk: dict, practice_id: str) -> CustomHtml:
    """custom_text 块：净化 + 资产 src 解析（HTML 侧原样输出，Word 侧解析）。"""
    html = workbook_layout.sanitize_custom_html(blk.get("html") or "")
    html = workbook_layout.resolve_custom_asset_srcs(
        html, practice_id,
        lambda name: (practice_service.practice_assets_dir(practice_id) / name).as_uri())
    return CustomHtml(html=html, align=blk.get("align") or "left")


# ── 练习 → Block（唯一入口） ──────────────────────────────────────────

def parse_rich_document(pq) -> dict | None:
    """题目富文档（可解析时）；无文档/解析失败返回 None → 旧内容块回退。"""
    if not pq.rich_document:
        return None
    try:
        doc = json.loads(pq.rich_document)
    except (TypeError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) and doc.get("type") == "doc" else None


def question_prefix(pq, show_score: bool, number: int | None = None) -> str:
    """题号前缀（整册序号可选覆盖）；分值按设置并入。"""
    no = pq.question_number if number is None else number
    prefix = f"{no}. "
    if show_score and pq.score is not None:
        prefix += f"（{pq.score:g} 分）"
    return prefix


def question_blocks(pq, prefix: str) -> list[Block]:
    """单题 → Block 序列（富文档优先，旧内容块回退）。"""
    doc = parse_rich_document(pq)
    if doc is not None:
        blocks = blocks_from_rich_doc(doc)
    else:
        blocks = blocks_from_legacy(sorted(pq.blocks, key=lambda b: b.position))
    return with_prefix(blocks, prefix)


def build_practice_ir(practice, practice_id: str, settings: dict) -> list[Block]:
    """练习 → Block 序列：页头（标题/副标题/总分/信息栏）+ 正文。

    `settings` 由 `render_service.render_settings` 产出，两个渲染器共用同一份，
    因此「字体、段落、分页」映射不必各自再推一遍。
    """
    out: list[Block] = [Heading(level="title", text=practice.title or "")]
    if practice.subtitle:
        out.append(Heading(level="subtitle", text=practice.subtitle))

    total = sum(pq.score or 0 for sec in practice.sections for pq in sec.questions)
    if settings.get("show_total_score") and total > 0:
        out.append(TotalScore(text=f"满分：{total:g} 分"))
    if settings.get("show_info_bar"):
        out.append(InfoBar(text=INFO_BAR_TEXT,
                           align=settings.get("info_bar_align", "left")))

    show_score = bool(settings.get("show_score"))
    if practice.layout_document:
        out.extend(_layout_blocks(practice, practice_id, show_score))
    else:
        for section in practice.sections:
            if section.start_on_new_page:
                out.append(PageBreak())
            if section.show_title:
                out.append(SectionTitle(text=section.title))
            for pq in section.questions:
                out.append(QuestionGroup(
                    blocks=question_blocks(pq, question_prefix(pq, show_score))))
    return out


def _layout_blocks(practice, practice_id: str, show_score: bool) -> list[Block]:
    """整册布局块序列 → Block（小节带「一、二、」序号，题目整册连续编号）。"""
    out: list[Block] = []
    qmap = {pq.id: pq for sec in practice.sections for pq in sec.questions}
    q_no, sub_no = 0, 0
    for blk in practice.layout_document or []:
        t = blk.get("type")
        if t == "subtitle":
            sub_no += 1
            if blk.get("start_on_new_page"):
                out.append(PageBreak())
            if blk.get("show_title", True):
                label = workbook_layout.section_label(sub_no)
                out.append(SectionTitle(text=f"{label}、{blk.get('title') or '小节'}"))
        elif t == "question_ref":
            pq = qmap.get(blk.get("question_id"))
            if pq is None:
                continue
            q_no += 1
            out.append(QuestionGroup(
                blocks=question_blocks(pq, question_prefix(pq, show_score, number=q_no))))
        elif t == "custom_text":
            out.append(custom_html_block(blk, practice_id))
        elif t == "spacer":
            out.append(Spacer(height_px=max(int(blk.get("height") or 20), 4)))
        elif t == "page_break":
            out.append(PageBreak())
    return out


# ── IR → HTML（预览 / PDF；Word 侧见 docx_export） ─────────────────────

_MARK_TAGS = (("bold", "b"), ("italic", "i"), ("underline", "u"),
              ("strike", "s"), ("superscript", "sup"), ("subscript", "sub"))


def _textstyle_css(marks: Marks) -> str:
    parts: list[str] = []
    if marks.font_family:
        parts.append(f"font-family:{typography.css_font_family(marks.font_family)}")
    if isinstance(marks.font_size, (int, float)):
        parts.append(f"font-size:{marks.font_size:g}pt")
    if marks.color:
        parts.append(f"color:{marks.color}")
    return ";".join(parts)


def _marks_html(inner: str, marks: Marks) -> str:
    for flag, tag in _MARK_TAGS:
        if getattr(marks, flag):
            inner = f"<{tag}>{inner}</{tag}>"
    style = _textstyle_css(marks)
    if style:
        # 样式值含双引号（font-family 链），写入属性必须转义
        inner = f'<span style="{_html.escape(style, quote=True)}">{inner}</span>'
    return inner


def _asset_uri(src: str, assets: Path) -> str:
    """asset://practice/xxx → 本地文件 URI；其余（/api/…）原样。"""
    if src.startswith("asset://practice/"):
        return (assets / src.removeprefix("asset://practice/")).as_uri()
    return src


def runs_html(runs, assets: Path) -> str:
    """行内 run 序列 → HTML（公式保留 $ 定界符交给 KaTeX 自动渲染）。"""
    out: list[str] = []
    for r in runs or []:
        if isinstance(r, Text):
            out.append(_marks_html(_html.escape(r.text), r.marks))
        elif isinstance(r, HardBreak):
            out.append("<br>")
        elif isinstance(r, InlineImage):
            out.append(f'<img src="{_asset_uri(r.src, assets)}" '
                       f'style="max-height:3.4em;vertical-align:middle">')
        elif isinstance(r, InlineFormula):
            delim = "$$" if r.display else "$"
            out.append(f"{delim}{_html.escape(r.latex)}{delim}")
    return "".join(out)


def _paragraph_style_css(attrs: dict) -> str:
    """段落属性 → 内联样式（只输出显式设置项；缺省 = 跟随练习默认）。"""
    parts: list[str] = []
    if attrs.get("textAlign"):
        parts.append(f"text-align:{attrs['textAlign']}")
    if attrs.get("lineHeight"):
        parts.append(f"line-height:{attrs['lineHeight']}")
    if attrs.get("spaceBefore"):
        parts.append(f"margin-top:{attrs['spaceBefore'] * 4 / 3:g}px")   # pt → px
    if attrs.get("spaceAfter"):
        parts.append(f"margin-bottom:{attrs['spaceAfter'] * 4 / 3:g}px")
    if attrs.get("firstLineIndent"):
        parts.append("text-indent:2em")
    if attrs.get("indent"):
        parts.append(f"margin-left:{attrs['indent'] * 2}em")
    return ";".join(parts)


def _width_css(width) -> str:
    if not width or width == "fit":
        return FIT_STYLE
    if isinstance(width, (int, float)):
        return f"width:{width:g}%"
    return f"width:{width}"


def _image_html(img: ImageBlock, assets: Path) -> str:
    return (f'<div class="q-img" style="text-align:{img.align}">'
            f'<img src="{_asset_uri(img.src, assets)}" '
            f'style="{_width_css(img.width)};height:auto"></div>')


def block_html(b: Block, assets: Path) -> str:
    if isinstance(b, Paragraph):
        style = _paragraph_style_css(b.style or {})
        body = runs_html(b.runs, assets)
        attr = f' style="{style}"' if style else ""
        return f'<div class="q-text"{attr}>{body}</div>'
    if isinstance(b, ImageBlock):
        return _image_html(b, assets)
    if isinstance(b, ImageRow):
        row_style = ""
        scale = b.images[0].scale if b.images else None
        if isinstance(scale, (int, float)) and 0 < scale < 100:
            row_style = f' style="width:{scale:g}%;margin:4px auto"'
        cells = "".join(
            f'<div class="q-img-cell"><img src="{_asset_uri(i.src, assets)}" '
            f'style="max-width:100%;height:auto"></div>' for i in b.images)
        return f'<div class="q-img-row"{row_style}>{cells}</div>'
    if isinstance(b, FormulaBlock):
        latex = _html.escape(b.latex)
        return f'<div class="q-formula" style="text-align:center;margin:4px 0">$${latex}$$</div>'
    if isinstance(b, OptionGroup):
        rows = "".join(
            f'<div class="q-option"><span class="opt-label">{_html.escape(label)}.</span>'
            f'{runs_html(runs, assets)}</div>' for label, runs in b.options)
        return f'<div class="q-options">{rows}</div>'
    if isinstance(b, AnswerSpace):
        lines = '<div class="space-line"></div>' * b.rows
        return f'<div class="answer-space">{lines}</div>'
    if isinstance(b, HorizontalRule):
        return '<hr class="q-hr">'
    if isinstance(b, ListBlock):
        tag = "ol" if b.ordered else "ul"
        items = []
        for blocks in b.items:
            segs = [block_html(x, assets) if isinstance(x, ListBlock)
                    else runs_html(x.runs, assets) for x in blocks]
            items.append("<li>" + "<br>".join(segs) + "</li>")
        return f'<{tag} class="q-list">{"".join(items)}</{tag}>'
    if isinstance(b, Spacer):
        return f'<div class="q-spacer" style="height:{b.height_px}px"></div>'
    if isinstance(b, PageBreak):
        return '<div class="new-page"></div>'
    if isinstance(b, Heading):
        cls = "p-title" if b.level == "title" else "p-subtitle"
        return f'<div class="{cls}">{_html.escape(b.text)}</div>'
    if isinstance(b, TotalScore):
        return f'<div class="p-total">{_html.escape(b.text)}</div>'
    if isinstance(b, InfoBar):
        return (f'<div class="info-bar" style="text-align:{b.align}">'
                f'{_html.escape(b.text)}</div>')
    if isinstance(b, SectionTitle):
        return f'<div class="section-title">{_html.escape(b.text)}</div>'
    if isinstance(b, CustomHtml):
        return f'<div class="q-custom" style="text-align:{b.align}">{b.html}</div>'
    if isinstance(b, QuestionGroup):
        return f'<div class="question">{"".join(block_html(x, assets) for x in b.blocks)}</div>'
    return ""


def blocks_html(blocks: list[Block], practice_id: str) -> str:
    assets = practice_service.practice_assets_dir(practice_id)
    return "".join(block_html(b, assets) for b in blocks)


def question_html_from_ir(doc: dict, practice_id: str, prefix: str) -> str:
    """单题富文档 → 题目体 HTML（保留旧 `doc_render.question_html` 语义）。"""
    return blocks_html(with_prefix(blocks_from_rich_doc(doc), prefix), practice_id)
