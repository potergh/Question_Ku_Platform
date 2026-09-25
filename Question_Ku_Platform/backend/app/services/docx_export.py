"""Word 导出：练习块 → 可编辑 docx（仅学生版，规格 11.2）。"""

import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.dml.color import RGBColor
from docx.oxml.ns import qn, nsdecls
from docx.oxml import OxmlElement, parse_xml
from docx.shared import Cm, Mm, Pt

from app.services import practice_service, render_ir, typography
from app.services.render_service import render_settings, katex_dist_dir

A4_W, A4_H = Cm(21), Cm(29.7)
MAX_IMG_H = Cm(24)       # 竖长图高度硬封顶（A4 内容区约 24.7cm）
FIT_MAX_H = Cm(8)        # fit 默认上限：与预览同源，避免图片普遍偏大/忽大忽小


# 公式降级渲染页：与预览/PDF 同源 KaTeX，离线 file:// 加载，白底供截图（阶段 3）
_FORMULA_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8">'
    '<link rel="stylesheet" href="{dist}/katex.min.css">'
    '<script src="{dist}/katex.min.js"></script>'
    '<style>html,body{{margin:0;padding:0;background:#fff}}'
    '#f{{display:inline-block;padding:8px}}</style></head>'
    '<body><div id="f"></div></body></html>')


class _FormulaFallback:
    """OMML 转换失败时把公式渲染为图片（懒启动单浏览器会话 + 同公式缓存）。
    渲染失败才退回 LaTeX 原文；降级清单经响应头提示用户（不静默丢失）。"""

    def __init__(self):
        self.degraded: list[str] = []   # 降级为图片的公式（LaTeX 原文）
        self._cache: dict = {}
        self._pw = self._browser = self._page = None
        self._tmp = None
        self._dead = False              # 启动/渲染失败后不再重试（退回原文兼容旧行为）

    def render(self, latex: str, display: bool):
        """返回 PNG 字节；失败返回 None。"""
        import shutil
        import tempfile
        key = (latex, display)
        if key in self._cache:
            return self._cache[key]
        if self._dead:
            return None
        try:
            if self._page is None:
                from playwright.sync_api import sync_playwright
                # 临时目录 + 相对路径加载（set_content 下 file:// 脚本不执行）
                self._tmp = Path(tempfile.mkdtemp())
                shutil.copytree(katex_dist_dir(), self._tmp / "katex")
                (self._tmp / "formula.html").write_text(
                    _FORMULA_PAGE.format(dist="katex", dist2="katex"), encoding="utf-8")
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch()
                ctx = self._browser.new_context(device_scale_factor=2)
                self._page = ctx.new_page()
                self._page.goto((self._tmp / "formula.html").as_uri(), wait_until="load")
            ok = self._page.evaluate(
                "({latex, display}) => { try {"
                "katex.render(latex, document.getElementById('f'),"
                "{displayMode: display, throwOnError: true}); return true;"
                "} catch (e) { return false; } }", {"latex": latex, "display": display})
            if not ok:
                self._cache[key] = None
                return None
            png = self._page.query_selector("#f").screenshot(type="png")
            self._cache[key] = png
            return png
        except Exception:
            self._dead = True
            self._cache[key] = None
            return None

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            if self._tmp:
                import shutil
                shutil.rmtree(self._tmp, ignore_errors=True)


def _insert_formula_image(paragraph, png: bytes, latex: str, display: bool, default_size: float):
    """公式降级图片写入段落：行内随字号定高，独立按宽高比限宽；alt 文字保留 LaTeX 便于追溯。"""
    from PIL import Image
    stream = io.BytesIO(png)
    with Image.open(io.BytesIO(png)) as im:
        px_w, px_h = im.size
    run = paragraph.add_run()
    if display:
        emu_w, emu_h = px_w * 914400 // 192, px_h * 914400 // 192   # 2x 截图 → 96dpi 折算
        width = min(emu_w, int(Cm(15)))
        run.add_picture(stream, width=width)
    else:
        run.add_picture(stream, height=Pt(default_size * 1.5))
    try:   # Word 替代文字：保留原始 LaTeX（图片降级后仍可追溯/手工重建）
        shape = paragraph.runs[-1]._r.find(qn("w:drawing")).find(qn("wp:inline"))
        shape.find(qn("wp:docPr")).set("descr", latex)
    except Exception:
        pass


def build_docx(practice, practice_id: str) -> tuple[bytes, list[str]]:
    """返回 (docx 字节, 降级为图片的公式清单)。"""
    fb = _FormulaFallback()
    try:
        return _build_docx_inner(practice, practice_id, fb), fb.degraded
    finally:
        fb.close()


def _build_docx_inner(practice, practice_id: str, fb: "_FormulaFallback") -> bytes:
    s = render_settings(practice)
    margins = s["margins"]
    landscape = s.get("orientation", "portrait") == "landscape"
    content_width = (A4_H if landscape else A4_W) - Mm(margins["left"]) - Mm(margins["right"])

    doc = Document()
    # 全局默认样式（阶段 2）：中文白名单字体 + 西文 Times New Roman，设在 Normal 样式上全文生效；
    # 未局部覆盖的内容跟随默认，改全局即生效；局部 marks 在 run 层覆盖。
    ds = s["default_style"]
    normal = doc.styles["Normal"]
    normal.font.name = ds["font_family"] if ds["font_family"] in typography.EN_FONT_CHAIN else typography.DEFAULT_EN_FONT
    normal._element.rPr.rFonts.set(
        qn("w:eastAsia"),
        typography.word_font_name(
            ds["font_family"] if ds["font_family"] in typography.CN_FONT_CHAIN
            else typography.DEFAULT_CN_FONT))
    normal.font.size = Pt(ds["font_size"])
    normal.paragraph_format.line_spacing = ds["line_height"]
    sec = doc.sections[0]
    if landscape:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = A4_H, A4_W
    else:
        sec.orientation = WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = A4_W, A4_H
    sec.top_margin = Mm(margins["top"])
    sec.bottom_margin = Mm(margins["bottom"])
    sec.left_margin = Mm(margins["left"])
    sec.right_margin = Mm(margins["right"])
    _apply_header_footer(sec, s, content_width)

    # F07 Task 7.8：正文（含标题/副标题/总分/信息栏等页头块）全部由统一中间结构
    # 驱动，与 HTML/PDF 同源；此处不再自行推断题目结构与顺序。
    blocks = render_ir.build_practice_ir(practice, practice_id, s)
    ctx = _DocxCtx(
        assets=practice_service.practice_assets_dir(practice_id),
        content_width=content_width, s=s, fb=fb,
        default_size=s["default_style"]["font_size"],
    )
    _add_blocks(doc, blocks, ctx)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _add_custom_html(doc, html: str, assets: Path, content_width):
    """自定义内容简单富文本 → Word 段落（p/div/br/strong/em/u/img）。

    `html` 由 `render_ir.custom_html_block` 产出：已净化、资产 src 已解析，
    本处不再重复净化（重复净化会破坏已解析的 file:// 引用）。
    """
    handler = _CustomHtmlDocx(doc, assets, content_width)
    handler.feed(html)
    handler.close()


class _CustomHtmlDocx(HTMLParser):
    """自定义内容 HTML → Word：块级标签起段，行内 strong/em/u 记入 run 样式，img 按内容宽插入。"""
    _BLOCK = {"p", "div", "h1", "h2", "h3", "li", "ol", "ul"}

    def __init__(self, doc, assets: Path, content_width):
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self.assets = assets
        self.content_width = content_width
        self._stack: list = []
        self._runs: list = []
        self._para = None

    def _new_para(self):
        if self._para is None:
            self._para = self.doc.add_paragraph()
        return self._para

    def _flush(self, br: bool = False):
        para = self._new_para()
        for text, b, i, u in self._runs:
            if not text:
                continue
            r = para.add_run(text)
            r.bold = b
            r.italic = i
            r.underline = u
            _set_cn_font(r)
        self._runs = []
        if br:
            para.add_run().add_break()

    def _close_para(self):
        self._flush()
        self._para = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._BLOCK:
            self._close_para()
            self._new_para()
            if tag.startswith("h") and "b" not in self._stack:
                self._stack.append("b")
        elif tag == "br":
            self._flush(br=True)
        elif tag == "img":
            self._flush()
            src = dict(attrs).get("src", "")
            path = _asset_local_path(src, self.assets)
            if path is not None:
                self._add_img(path)
        elif tag in ("strong", "b"):
            self._stack.append("b")
        elif tag in ("em", "i"):
            self._stack.append("i")
        elif tag == "u":
            self._stack.append("u")
        elif tag in ("span", "s", "sub", "sup"):
            self._stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._BLOCK:
            self._close_para()
            return
        for fmt in ("b", "i", "u", "span", "s", "sub", "sup"):
            if tag == fmt and fmt in self._stack:
                self._stack.remove(fmt)

    def handle_data(self, data):
        if not data:
            return
        self._new_para()
        for is_math, text, display in _split_math(data):
            if is_math:
                el = _latex_to_omml(text, display)
                if el is not None:
                    self._flush()
                    self._para._p.append(el)
                    continue
                text = f"{'$$' if display else '$'}{text}{'$$' if display else '$'}"
            self._runs.append((text, "b" in self._stack, "i" in self._stack, "u" in self._stack))

    def close(self):
        super().close()
        self._close_para()

    def _add_img(self, fp: Path):
        if not fp.exists():
            return
        try:
            from PIL import Image
            from docx.shared import Cm
            im = Image.open(fp)
            px_w, px_h = im.size
            max_w = min(int(Cm(8)), int(self.content_width))
            if px_w <= 0 or max_w <= 0:
                return
            ratio = max_w / (px_w * 914400 // 96)
            h = int((px_h * 914400 // 96) * ratio)
            r = self._new_para().add_run()
            with io.BytesIO(fp.read_bytes()) as stream:
                r.add_picture(stream, width=max_w, height=h)
        except Exception:
            pass


def _set_cn_font(run, name: str | None = None):
    """中文用指定字体，西文统一 Times New Roman。

    name 是白名单**显示名**（如「思源黑体」），过一遍 word_font_name 换成
    Word 能解析的族名 —— 直接写显示名会让 Word 找不到字体并静默回退。
    """
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(
        qn("w:eastAsia"), typography.word_font_name(name or typography.DEFAULT_CN_FONT))


def _set_run_font(run, name: str):
    """白名单字体 → run：中文字体写东亚属性，西文写 ascii（中英混排各取所需）。"""
    if name in typography.CN_FONT_CHAIN:
        run.font.name = typography.DEFAULT_EN_FONT
        run._element.rPr.rFonts.set(qn("w:eastAsia"), typography.word_font_name(name))
    else:
        run.font.name = name


def _apply_header_footer(section, s: dict, content_width):
    """阶段 6：页眉/页脚三栏 + 首页不同 + 动态字段。
    header 为 dict（enabled 决定是否显示）；footer 为 None 时沿用旧 show_page_number 页码行为。"""
    header = s.get("header")
    footer = s.get("footer")
    if header and header.get("enabled"):
        _fill_zone(section.header.paragraphs[0], header, content_width, top=True)
    if footer is None:
        if s.get("show_page_number", True):
            _add_page_number(section)
    elif footer.get("enabled"):
        _fill_zone(section.footer.paragraphs[0], footer, content_width, top=False)
    first_hidden_header = bool(header and header.get("enabled")
                               and header.get("first_page_different") and header.get("first_hidden"))
    first_hidden_footer = bool(footer and footer.get("enabled") and footer.get("first_hidden"))
    if first_hidden_header or first_hidden_footer:
        section.different_first_page_header_footer = True   # 首页页眉/页脚保持 Word 默认空
    if first_hidden_header:
        section.first_page_header.is_linked_to_previous = False   # 创建独立空首页页眉
    if first_hidden_footer:
        section.first_page_footer.is_linked_to_previous = False   # 创建独立空首页页脚


def _fill_zone(p, zone: dict, content_width, top: bool):
    """把三栏文本写入页眉/页脚段落：左对齐 + 居中 tab + 右对齐 tab + 可选分隔线。"""
    fs = Pt(int(zone.get("font_size", 9)))
    if zone.get("line"):
        pPr = p._p.get_or_add_pPr()
        pbdr = OxmlElement("w:pBdr")
        edge = "bottom" if top else "top"
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "6")
        el.set(qn("w:space"), "1")
        el.set(qn("w:color"), "999999")
        pbdr.append(el)
        pPr.append(pbdr)
    tabs = p.paragraph_format.tab_stops
    tabs.add_tab_stop(int(content_width) // 2, WD_TAB_ALIGNMENT.CENTER)
    tabs.add_tab_stop(int(content_width), WD_TAB_ALIGNMENT.RIGHT)
    for key in ("left", "center", "right"):
        text = zone.get(key, "")
        if not text:
            continue
        if key != "left":
            p.add_run().add_tab()
        _add_zone_text(p, text, fs)


def _add_zone_text(p, text: str, fs):
    """把栏文本写入段落：普通文本设字号/中文字体；{page}/{total} → PAGE/NUMPAGES 域。"""
    for part in re.split(r"(\{page\}|\{total\})", text):
        if not part:
            continue
        if part == "{page}":
            _add_field(p, "PAGE", fs)
        elif part == "{total}":
            _add_field(p, "NUMPAGES", fs)
        else:
            run = p.add_run(part)
            run.font.size = fs
            _set_cn_font(run)


def _add_field(p, instr: str, fs):
    """向段落追加一个 Word 域（PAGE/NUMPAGES）。"""
    run = p.add_run()
    for tag, attr, val in [("w:fldChar", "begin", None), ("w:instrText", None, instr),
                           ("w:fldChar", "end", None)]:
        el = OxmlElement(tag)
        if tag == "w:fldChar":
            el.set(qn("w:fldCharType"), attr)
        else:
            el.text = val
        run._r.append(el)
    run.font.size = fs
    _set_cn_font(run)


def _add_page_number(section):
    """页脚居中插入 PAGE 域（Word 打开后显示真实页码）。"""
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for tag, attr, val in [("w:fldChar", "begin", None), ("w:instrText", None, "PAGE"),
                           ("w:fldChar", "end", None)]:
        el = OxmlElement(tag)
        if tag == "w:fldChar":
            el.set(qn("w:fldCharType"), attr)
        else:
            el.text = val
        run._r.append(el)


_ALIGN_MAP = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
              "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}


# ---------------- F07 Task 7.8：IR → Word（与 HTML/PDF 同源） ----------------

@dataclass
class _DocxCtx:
    """Word 渲染上下文：一次导出内共享的资产目录与页面度量。"""

    assets: Path
    content_width: int
    s: dict
    fb: "_FormulaFallback"
    default_size: float


def _add_blocks(doc, blocks, ctx: "_DocxCtx") -> None:
    for b in blocks:
        _add_block(doc, b, ctx)


def _add_block(doc, b, ctx: "_DocxCtx") -> None:
    """IR 块 → Word。结构判断已在 render_ir 完成，此处只做格式投影。"""
    if isinstance(b, render_ir.QuestionGroup):
        _add_blocks(doc, b.blocks, ctx)
    elif isinstance(b, render_ir.Heading):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if b.level == "title":
            run = p.add_run(b.text)
            run.bold = True
            run.font.size = Pt(18)
            _set_cn_font(run)
        else:
            p.add_run(b.text)
    elif isinstance(b, render_ir.TotalScore):
        p = doc.add_paragraph(b.text)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif isinstance(b, render_ir.InfoBar):
        p = doc.add_paragraph(b.text)
        p.alignment = _ALIGN_MAP.get(b.align, WD_ALIGN_PARAGRAPH.LEFT)
    elif isinstance(b, render_ir.SectionTitle):
        sp = doc.add_paragraph()
        sr = sp.add_run(b.text)
        sr.bold = True
        sr.font.size = Pt(13)
        _set_cn_font(sr)
    elif isinstance(b, render_ir.Paragraph):
        p = doc.add_paragraph()
        _apply_para_attrs(p, b.style or {}, ctx.default_size)
        _add_runs(p, b.runs, ctx)
    elif isinstance(b, render_ir.ImageBlock):
        _add_image(doc, b.src, {"align": b.align, "width": b.width},
                   ctx.assets, ctx.content_width)
    elif isinstance(b, render_ir.ImageRow):
        _add_image_row(doc, [(i.src, {"scale": i.scale}) for i in b.images],
                       ctx.assets, ctx.content_width)
    elif isinstance(b, render_ir.FormulaBlock):
        fp = doc.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_formula(fp, b.latex, True, ctx.fb, ctx.default_size)
    elif isinstance(b, render_ir.OptionGroup):
        for label, runs in b.options:
            op = doc.add_paragraph()
            op.paragraph_format.left_indent = Cm(0.74)
            op.add_run(f"{label}. ")
            _add_runs(op, runs, ctx)
    elif isinstance(b, render_ir.AnswerSpace):
        for _ in range(b.rows):
            doc.add_paragraph("")
    elif isinstance(b, render_ir.HorizontalRule):
        _add_horizontal_rule(doc)
    elif isinstance(b, render_ir.ListBlock):
        _add_list(doc, b, ctx, 0)
    elif isinstance(b, render_ir.Spacer):
        sp = doc.add_paragraph("")
        sp.paragraph_format.space_before = Pt(b.height_px * 0.75)
        sp.paragraph_format.space_after = Pt(0)
    elif isinstance(b, render_ir.PageBreak):
        bp = doc.add_paragraph()
        bp.add_run().add_break(WD_BREAK.PAGE)
    elif isinstance(b, render_ir.CustomHtml):
        _add_custom_html(doc, b.html, ctx.assets, ctx.content_width)


def _add_list(doc, node, ctx: "_DocxCtx", depth: int):
    """列表 → 缩进段落 + 符号/编号前缀（Word 原生列表样式不在首版范围）。"""
    for i, blocks in enumerate(node.items):
        first = True
        for x in blocks:
            if isinstance(x, render_ir.Paragraph):
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.74 * (depth + 1))
                if first:
                    p.add_run(f"{i + 1}. " if node.ordered else "• ")
                    first = False
                _add_runs(p, x.runs, ctx)
            elif isinstance(x, render_ir.ListBlock):
                _add_list(doc, x, ctx, depth + 1)


def _inline_img_pct(width):
    """行内图 width → 百分比数字（0~100）；None/'fit'/非法 → None（走默认小图高）。"""
    if isinstance(width, bool):
        return None
    if isinstance(width, (int, float)):
        return float(width) or None
    if isinstance(width, str) and width.endswith("%"):
        try:
            return float(width.removesuffix("%")) or None
        except ValueError:
            return None
    return None


def _add_runs(paragraph, runs, ctx: "_DocxCtx"):
    """行内 run → Word：marks → run 属性；公式 → OMML（失败降级图片）；行内图随基线。"""
    for r in runs or []:
        if isinstance(r, render_ir.Text):
            _apply_marks(paragraph.add_run(r.text), r.marks)
        elif isinstance(r, render_ir.HardBreak):
            paragraph.add_run().add_break(WD_BREAK.LINE)
        elif isinstance(r, render_ir.InlineImage):
            name = r.src.removeprefix("asset://practice/")
            path = ctx.assets / name
            if not path.exists():
                paragraph.add_run(f"[图缺失:{name}]")
                continue
            run = paragraph.add_run()
            # 有 width（百分比）→ 按内容宽折算，与块图一致；否则沿用默认行内小图高 0.9cm
            pct = _inline_img_pct(r.width)
            if pct is not None:
                run.add_picture(_picture_source(path), width=int(ctx.content_width * pct / 100))
            else:
                run.add_picture(_picture_source(path), height=Cm(0.9))
        elif isinstance(r, render_ir.InlineFormula):
            _add_formula(paragraph, r.latex, r.display, ctx.fb, ctx.default_size)


def _add_horizontal_rule(doc):
    """横线：一个带下边框的段落（与预览/PDF 的 hr 视觉一致）。"""
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")      # 1pt 实线（sz 以 1/8 pt 计）
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    pBdr.append(bottom)
    pPr.append(pBdr)
    return p


def _add_formula(paragraph, latex: str, display: bool, fb, default_size: float):
    """公式三级兜底：OMML 原生（可继续编辑）→ 图片降级（保显示，记入降级清单）→ LaTeX 原文。"""
    el = _latex_to_omml(latex, display)
    if el is not None:
        paragraph._p.append(el)
        return
    png = fb.render(latex, display) if fb is not None else None
    if png:
        _insert_formula_image(paragraph, png, latex, display, default_size)
        fb.degraded.append(latex)
    else:
        paragraph.add_run(("$$" if display else "$") + latex + ("$$" if display else "$"))


def _apply_marks(run, marks: "render_ir.Marks"):
    """IR 行内格式（Marks）→ Word run 属性。"""
    if not marks:
        return
    if marks.bold:
        run.bold = True
    if marks.italic:
        run.italic = True
    if marks.underline:
        run.underline = True
    if marks.strike:
        run.font.strike = True
    if marks.superscript:
        run.font.superscript = True
    if marks.subscript:
        run.font.subscript = True
    if marks.font_family:
        _set_run_font(run, marks.font_family)
    if isinstance(marks.font_size, (int, float)):
        run.font.size = Pt(marks.font_size)
    if marks.color:
        run.font.color.rgb = RGBColor.from_string(marks.color.lstrip("#"))


def _apply_para_attrs(p, attrs: dict, default_size: float):
    if attrs.get("textAlign"):
        p.alignment = _ALIGN_MAP.get(attrs["textAlign"])
    if attrs.get("lineHeight"):
        p.paragraph_format.line_spacing = attrs["lineHeight"]
    if attrs.get("spaceBefore"):
        p.paragraph_format.space_before = Pt(attrs["spaceBefore"])
    if attrs.get("spaceAfter"):
        p.paragraph_format.space_after = Pt(attrs["spaceAfter"])
    if attrs.get("firstLineIndent"):
        p.paragraph_format.first_line_indent = Pt(2 * default_size)   # 首行缩进两字符（随默认字号）
    if attrs.get("indent"):
        p.paragraph_format.left_indent = Cm(0.74 * attrs["indent"])


# 公式段：$$…$$ / \[…\] 为行间，$…$ / \(…\) 为行内（先长后短，正则分支顺序即优先级）
_MATH_RE = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$([^\$\n]+?)\$", re.S)


def _split_math(content: str):
    """内容切分为文字/公式段，返回 (是否公式, 文本, 是否行间)。"""
    segs, last = [], 0
    for m in _MATH_RE.finditer(content):
        if m.start() > last:
            segs.append((False, content[last:m.start()], False))
        if m.group(1) is not None or m.group(2) is not None:
            segs.append((True, m.group(1) or m.group(2), True))
        else:
            segs.append((True, m.group(3) or m.group(4), False))
        last = m.end()
    if last < len(content):
        segs.append((False, content[last:], False))
    return segs


def _latex_to_omml(tex: str, display: bool):
    """LaTeX → OMML 元素（Word 原生公式）；转换失败返回 None，调用方退回原文。
    注：mathml2omml 对个别命令（如 \\vec）会产出标签不闭合的坏 OMML，
    parse_xml 一并纳入 try——坏 OMML 按转换失败处理，走图片降级，避免污染整个 docx。"""
    try:
        import latex2mathml.converter
        import mathml2omml
        omml = mathml2omml.convert(latex2mathml.converter.convert(tex.strip()))
        if display:
            omml = f"<m:oMathPara>{omml}</m:oMathPara>"
        return parse_xml(f'<root {nsdecls("m")}>{omml}</root>')[0]
    except Exception:
        return None


def _asset_local_path(src: str, assets: Path) -> Path | None:
    """资产引用 → 本地路径。

    - `asset://practice/<name>`：题目/选项内联图（IR 未解析，保留资产语义）
    - `file://...`：整册自定义内容（IR 已按练习资产目录解析成文件 URI）
    """
    if not src:
        return None
    if src.startswith("asset://practice/"):
        return assets / src.removeprefix("asset://practice/")
    if src.startswith("file:"):
        from urllib.parse import urlparse
        from urllib.request import url2pathname
        return Path(url2pathname(urlparse(src).path))
    return None


def _add_image(doc, src: str, style: dict, assets: Path, content_width):
    name = (src or "").removeprefix("asset://practice/")
    path = assets / name
    ip = doc.add_paragraph()
    align = style.get("align", "center")
    ip.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}.get(
        align, WD_ALIGN_PARAGRAPH.CENTER)
    if not path.exists():
        ip.add_run(f"[图片缺失：{name}]")
        return
    width = None
    w = style.get("width", "fit")
    if isinstance(w, (int, float)):
        width = content_width * w / 100
    elif isinstance(w, str) and w.endswith("%"):
        width = content_width * float(w.removesuffix("%")) / 100
    if width is None:   # fit：原尺寸，受默认上限（内容区 50% 宽 / 8cm 高）与硬封顶约束
        width = _fit_width(path, content_width)
    run = ip.add_run()
    run.add_picture(_picture_source(path), width=width)


def _add_image_row(doc, items, assets: Path, content_width):
    """连续图片并排：无边框单行表格，等宽列；单元格内居中且不超过列宽。items 为 (src, style) 序列。
    阶段 4：scale（整行等比缩放）→ 行总宽 = 内容宽 * scale%，等宽列随行变窄，表格保持居中。"""
    n = len(items)
    scale = (items[0][1] or {}).get("scale")
    row_w = content_width
    if isinstance(scale, (int, float)) and 0 < scale < 100:
        row_w = int(content_width * scale / 100)
    table = doc.add_table(rows=1, cols=n)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell_w = max(1, row_w // n)
    for i, (src, _) in enumerate(items):
        cell = table.rows[0].cells[i]
        cell.width = cell_w
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        name = (src or "").removeprefix("asset://practice/")
        path = assets / name
        if not path.exists():
            p.add_run(f"[图片缺失：{name}]")
            continue
        width = _fit_width(path, cell_w)
        p.add_run().add_picture(_picture_source(path), width=width)


def _natural_size(path: Path):
    """图片自然宽高（EMU）。忽略文件内嵌 dpi（各图 96/300 不一导致忽大忽小），统一按 96 折算。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            px_w, px_h = im.size
        return int(px_w / 96 * 914400), int(px_h / 96 * 914400)
    except Exception:
        return None


def _fit_width(path: Path, max_width, max_height=None):
    """fit：宽受 max_width 与默认上限（内容区 50%）双重封顶，高度封顶后再反推宽度；读不到尺寸保持原样。
    max_height：可选的高度封顶，先按它等比缩宽再走默认上限（阶段 4 行内高度封顶已由 scale 取代，仅保留参数兼容）。"""
    ns = _natural_size(path)
    if not ns:
        return None
    w, h = ns
    cap_w = min(max_width, int(max_width / 2))
    if max_height and h > max_height:
        w = int(w * max_height / h)
        h = max_height
    if h > FIT_MAX_H:
        w = int(w * FIT_MAX_H / h)
    if h > MAX_IMG_H:
        w = min(w, int(w * MAX_IMG_H / h))
    if w >= cap_w:
        return cap_w
    return w if (w != ns[0] or h != ns[1]) else None


def _picture_source(path: Path):
    """docx 只识别常见光栅格式；webp/avif 等（OCR 常见）先用 PIL 转 PNG 流。"""
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".ico"}:
        return str(path)
    from PIL import Image
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
