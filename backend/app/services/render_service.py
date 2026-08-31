"""Render service — 练习块 → 独立 HTML（供 Playwright 出 PDF）。"""

import asyncio
import hashlib
import html as _html
import json
import re
import shutil
import tempfile
from pathlib import Path

from app.models.practice import Practice
from app.services import doc_render, practice_service, typography, workbook_layout

MARGIN_PRESETS = {"narrow": "15mm", "normal": "25mm", "wide": "32mm"}

PAGE_FOOTER = ('<div style="width:100%;text-align:center;font-size:8px;color:#555;">'
               '第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</div>')


def katex_dist_dir() -> Path:
    """frontend/node_modules/katex/dist（渲染时整目录拷入临时渲染目录）。"""
    d = Path(__file__).resolve().parents[3] / "frontend" / "node_modules" / "katex" / "dist"
    if not d.exists():
        raise RuntimeError("KaTeX 未安装：请先在 frontend/ 执行 npm install")
    return d


def render_settings(practice: Practice) -> dict:
    """page_config → 渲染设置（含默认值）。"""
    cfg = practice.page_config or {}
    return {
        "margin": MARGIN_PRESETS.get(cfg.get("margin_preset", "normal"), "25mm"),
        "show_info_bar": cfg.get("show_info_bar", True),
        "show_page_number": cfg.get("show_page_number", True),
        "show_score": cfg.get("show_score", False),
        "show_total_score": cfg.get("show_total_score", False),
        "default_style": typography.practice_default_style(practice),   # 阶段 2 全局默认样式
    }


def _text_to_html(text: str) -> str:
    """Markdown-lite：转义后处理加粗/换行；LaTeX 定界符原样保留交给 KaTeX。"""
    s = _html.escape(text or "")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = s.replace("\n", "<br>")
    return s


def _img_tag(b, practice_id: str, style_attr: str) -> str:
    name = (b.content or "").removeprefix("asset://practice/")
    src = (practice_service.practice_assets_dir(practice_id) / name).as_uri()
    return f'<img src="{src}" style="{style_attr}">'


# fit 默认上限：宽不超内容区 50%、高不超 8cm（与 docx 导出同源，避免普遍偏大/忽大忽小）
FIT_STYLE = "max-width:50%;max-height:8cm"

# 选项/文本中的图片引用（含 Markdown 包装），渲染时转内联 <img>
_OPT_IMG_RE = re.compile(r"!\[[^\]]*\]\((asset://[^\s\)]+)\)|(asset://[^\s\)]+)")


def _inline_imgs_html(text: str, practice_id: str) -> str:
    """文字中的图片引用 → 内联 <img>（选项图）；其余文本正常转义。"""
    assets = practice_service.practice_assets_dir(practice_id)
    out: list[str] = []
    last = 0
    for m in _OPT_IMG_RE.finditer(text or ""):
        out.append(_text_to_html(text[last:m.start()]))
        name = (m.group(1) or m.group(2)).removeprefix("asset://practice/")
        src = (assets / name).as_uri()
        out.append(f'<img src="{src}" style="max-height:3.4em;vertical-align:middle">')
        last = m.end()
    out.append(_text_to_html((text or "")[last:]))
    return "".join(out)


def _block_html(b, practice_id: str) -> str:
    style = b.style_config or {}
    if b.block_type == "text":
        return f'<div class="q-text">{_text_to_html(b.content)}</div>'
    if b.block_type == "image":
        align = style.get("align", "center")
        w = style.get("width", "fit")
        width_css = FIT_STYLE if w == "fit" else f"width:{w}"
        return (f'<div class="q-img" style="text-align:{align}">'
                f'{_img_tag(b, practice_id, width_css + ";height:auto")}</div>')
    if b.block_type == "options":
        try:
            opts = json.loads(b.content) if b.content else []
        except (TypeError, json.JSONDecodeError):
            opts = []
        rows = "".join(
            f'<div class="q-option"><span class="opt-label">{_html.escape(o.get("label", ""))}.</span>'
            f'{_inline_imgs_html(o.get("content", ""), practice_id)}</div>' for o in opts)
        return f'<div class="q-options">{rows}</div>'
    if b.block_type == "answer_space":
        rows = int(style.get("rows", 0))
        lines = '<div class="space-line"></div>' * rows
        return f'<div class="answer-space">{lines}</div>'
    return ""  # answer/explanation 块学生版不输出（规格 11.2）


def build_practice_html(practice: Practice, practice_id: str) -> str:
    """页头（标题/副标题/总分/信息栏）+ 小节（标题/分页）+ 题目。"""
    s = render_settings(practice)
    head: list[str] = [f'<div class="p-title">{_html.escape(practice.title)}</div>']
    if practice.subtitle:
        head.append(f'<div class="p-subtitle">{_html.escape(practice.subtitle)}</div>')

    total_score = 0.0
    has_score = False
    for sec in practice.sections:
        for pq in sec.questions:
            if pq.score is not None:
                total_score += pq.score
                has_score = True
    if s["show_total_score"] and has_score:
        head.append(f'<div class="p-total">满分：{total_score:g} 分</div>')
    if s["show_info_bar"]:
        head.append('<div class="info-bar">姓名：____________　班级：____________　日期：____________</div>')

    if practice.layout_document:
        body = _layout_bodies(practice, s, practice_id)
    else:
        body = _section_bodies(practice, s)
    return _head_css(s["default_style"]) + '<body>' + "".join(head + body) + _katex_tags() + '</body></html>'


def _section_bodies(practice: Practice, s: dict) -> list[str]:
    out: list[str] = []
    for section in practice.sections:
        if section.start_on_new_page:
            out.append('<div class="new-page"></div>')
        if section.show_title:
            out.append(f'<div class="section-title">{_html.escape(section.title)}</div>')
        for pq in section.questions:
            prefix = f"{pq.question_number}. "
            if s["show_score"] and pq.score is not None:
                prefix += f"（{pq.score:g} 分）"
            doc = _parse_rich_doc(pq)
            if doc is not None:   # 阶段 2：富文档为真源（marks/段落属性只在此路径生效）
                out.append(f'<div class="question">{doc_render.question_html(doc, practice.id, prefix)}</div>')
                continue
            blocks = sorted(pq.blocks, key=lambda b: b.position)
            out.append(f'<div class="question">{_blocks_html(blocks, practice.id, prefix)}</div>')
    return out


def _custom_text_html(blk: dict, practice_id: str) -> str:
    html = workbook_layout.sanitize_custom_html(blk.get("html") or "")
    html = workbook_layout.resolve_custom_asset_srcs(
        html, practice_id, lambda name: (practice_service.practice_assets_dir(practice_id) / name).as_uri())
    align = blk.get("align") or "left"
    return f'<div class="q-custom" style="text-align:{align}">{html}</div>'


def _layout_bodies(practice: Practice, s: dict, practice_id: str) -> list[str]:
    """阶段 5：按整册布局块序列渲染（小节标题带"一、二、三"序号；题目整册连续题号；
    自定义内容/空白/分页符按序插入）。"""
    out: list[str] = []
    qmap = {pq.id: pq for sec in practice.sections for pq in sec.questions}
    q_no, sub_no = 0, 0
    for blk in practice.layout_document or []:
        t = blk.get("type")
        if t == "subtitle":
            sub_no += 1
            if blk.get("start_on_new_page"):
                out.append('<div class="new-page"></div>')
            if blk.get("show_title", True):
                title = blk.get("title") or "小节"
                num = workbook_layout.section_label(sub_no)
                out.append(f'<div class="section-title">{num}、{_html.escape(title)}</div>')
        elif t == "question_ref":
            pq = qmap.get(blk.get("question_id"))
            if pq is None:
                continue
            q_no += 1
            prefix = f"{q_no}. "
            if s["show_score"] and pq.score is not None:
                prefix += f"（{pq.score:g} 分）"
            doc = _parse_rich_doc(pq)
            if doc is not None:
                out.append(f'<div class="question">{doc_render.question_html(doc, practice.id, prefix)}</div>')
            else:
                blocks = sorted(pq.blocks, key=lambda b: b.position)
                out.append(f'<div class="question">{_blocks_html(blocks, practice.id, prefix)}</div>')
        elif t == "custom_text":
            out.append(_custom_text_html(blk, practice_id))
        elif t == "spacer":
            h = int(blk.get("height") or 20)
            out.append(f'<div class="q-spacer" style="height:{max(h, 4)}px"></div>')
        elif t == "page_break":
            out.append('<div class="new-page"></div>')
    return out


def _parse_rich_doc(pq):
    """题目富文档（可解析时）；无文档/解析失败返回 None → 旧块回退路径。"""
    if not pq.rich_document:
        return None
    try:
        doc = json.loads(pq.rich_document)
    except (TypeError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) and doc.get("type") == "doc" else None


def _blocks_html(blocks, practice_id: str, prefix: str) -> str:
    """题号/分值并入首个文字块（与题干同行）；连续图片并排一行。"""
    out: list[str] = []
    imgs: list = []
    prefix_used = False

    def flush_imgs():
        if not imgs:
            return
        if len(imgs) == 1:
            out.append(_block_html(imgs[0], practice_id))
        else:
            cells = "".join(f'<div class="q-img-cell">{_img_tag(b, practice_id, "max-width:100%;height:auto")}</div>'
                            for b in imgs)
            out.append(f'<div class="q-img-row">{cells}</div>')
        imgs.clear()

    for b in blocks:
        if b.block_type == "image":
            imgs.append(b)
            continue
        flush_imgs()
        if b.block_type == "text" and not prefix_used:
            out.append(f'<div class="q-text"><b>{_html.escape(prefix)}</b>{_text_to_html(b.content)}</div>')
            prefix_used = True
        else:
            out.append(_block_html(b, practice_id))
    flush_imgs()
    if not prefix_used:   # 无文字块（纯图片题）：题号单独一行并置顶
        out.insert(0, f'<div class="q-text"><b>{_html.escape(prefix)}</b></div>')
    return "".join(out)


def _head_css(default_style: dict | None = None) -> str:
    ds = default_style or typography.DEFAULT_STYLE
    family = typography.css_font_family(ds.get("font_family"))   # 西文 TNR 在前，中文白名单字体随后
    size = f"{ds.get('font_size', 10.5):g}pt"
    lh = ds.get("line_height", 1.7)
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>'
            f'body {{ font-family: {family}; font-size: {size};'
            f' line-height: {lh}; color: #000; margin: 0; }}'
            '.p-title { text-align: center; font-size: 18pt; font-weight: bold; margin-bottom: 4px; }'
            '.p-subtitle { text-align: center; font-size: 12pt; color: #333; margin-bottom: 8px; }'
            '.p-total { text-align: center; font-size: 10.5pt; margin-bottom: 6px; }'
            '.info-bar { margin: 8px 0 14px; font-size: 10.5pt; }'
            '.section-title { font-weight: bold; font-size: 12pt; margin: 14px 0 8px; }'
            '.new-page { page-break-before: always; }'
            '.question { margin-bottom: 12px; }'
            '.q-text { margin: 2px 0; }'
            '.q-img img { max-height: 420px; }'
            '.q-option img { max-height: 3.4em; }'
            '.q-img-row { display: flex; gap: 8px; justify-content: center; margin: 4px 0; }'
            '.q-img-cell { flex: 1 1 0; min-width: 0; text-align: center; }'
            '.q-img-cell img { max-width: 100%; max-height: 300px; height: auto; }'
            '.q-options { margin: 4px 0 4px 2em; }'
            '.q-option { margin: 1px 0; }'
            '.opt-label { margin-right: 4px; }'
            '.q-score { font-size: 9pt; }'
            '.answer-space { margin: 4px 0; }'
            # 阶段 3 补齐：独立公式跨页保护（公式整体不被拆到两页）+ 长公式不溢出容器
            '.q-formula { page-break-inside: avoid; break-inside: avoid; }'
            '.katex-display { page-break-inside: avoid; break-inside: avoid; }'
            'u { white-space: pre-wrap; }'   # 下划线填空位常为纯空格：防空白折叠导致下划线不可见
            '.q-hr { border: none; border-top: 1px solid #000; margin: 6px 0; }'   # 横线（填写线/分隔线）
            '.q-list { margin: 2px 0 2px 2em; padding: 0; }'
            '.q-list li { margin: 1px 0; }'
            '.space-line { height: 1.9em; }'   # 答题留白：纯空白不画横线（用户决策 2026-08-30）
            '.q-custom img { max-width: 100%; height: auto; }'   # 自定义内容图片不超内容区
            '</style></head>')


def _katex_tags() -> str:
    return ('<link rel="stylesheet" href="katex/katex.min.css">'
            '<script defer src="katex/katex.min.js"></script>'
            '<script defer src="katex/contrib/auto-render.min.js"></script>'
            '<script>window.addEventListener("DOMContentLoaded", function(){'
            'renderMathInElement(document.body, {delimiters:['
            '{left:"$$",right:"$$",display:true},{left:"\\\\[",right:"\\\\]",display:true},'
            '{left:"$",right:"$",display:false},{left:"\\\\(",right:"\\\\)",display:false}]});'
            # 阶段 3 补齐：长公式溢出检测——超出内容宽度的显示公式按比例缩放（zoom 影响布局），并记录统计
            'window.__katexLayout = {overflow:0, scaled:0, unhandled:0};'
            'document.querySelectorAll(".katex-display").forEach(function(el){'
            'var host = el.closest(".q-formula") || el.parentElement;'
            'if (!host) return;'
            'var katex = el.querySelector(".katex");'
            'if (!katex) return;'
            'var avail = host.clientWidth || host.parentElement.clientWidth || document.body.clientWidth;'
            'var w = katex.scrollWidth || katex.getBoundingClientRect().width;'
            'if (w > avail) {'
            '  window.__katexLayout.overflow++;'
            '  var scale = avail / w;'
            '  el.style.zoom = scale.toFixed(4);'
            '  window.__katexLayout.scaled++;'
            '  if (scale < 0.5) window.__katexLayout.unhandled++;'
            '}'
            '});'
            'window.__katexDone = true;});</script>')


async def render_pdf_bytes(html: str, settings: dict) -> bytes:
    """HTML → A4 PDF：工作线程内同步 Playwright，不依赖运行中循环类型。
    （Windows + --reload 下 uvicorn 0.52 默认 SelectorEventLoop 不支持 asyncio 子进程）"""
    return await asyncio.to_thread(_render_pdf_bytes_sync, html, settings)


def _render_pdf_bytes_sync(html: str, settings: dict) -> bytes:
    """临时目录内 practice.html + katex/ 子目录，file:// 加载（离线可用）。"""
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "practice.html").write_text(html, encoding="utf-8")
        shutil.copytree(katex_dist_dir(), root / "katex")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto((root / "practice.html").as_uri(), wait_until="load")
                page.wait_for_function("window.__katexDone === true", timeout=15000)
                margin = settings["margin"]
                # 页码脚注预留 10mm：Chromium pdf margin 只收数值长度，不支持 calc()
                bottom_mm = float(margin.removesuffix("mm")) + (10 if settings["show_page_number"] else 0)
                return page.pdf(
                    format="A4", print_background=True,
                    margin={"top": margin, "bottom": f"{bottom_mm}mm", "left": margin, "right": margin},
                    display_header_footer=settings["show_page_number"],
                    header_template="<div></div>", footer_template=PAGE_FOOTER,
                )
            finally:
                browser.close()


async def ensure_preview_pdf(practice_id: str, html: str, settings: dict) -> tuple[Path, str, int]:
    """缓存预览 PDF；sha 命中则跳过浏览器。返回 (路径, sha, 页数)。"""
    from app.services.preview_service import pdf_page_count
    sha = hashlib.sha1(html.encode("utf-8")).hexdigest()
    pdir = practice_service.practices_root() / practice_id
    pdf_path, meta_path = pdir / "preview.pdf", pdir / "preview_meta.json"
    if pdf_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("sha") == sha:
            return pdf_path, sha, meta["pages"]
    pdf = await render_pdf_bytes(html, settings)
    pdf_path.write_bytes(pdf)
    pages = pdf_page_count(pdf_path)
    meta_path.write_text(json.dumps({"sha": sha, "pages": pages}), encoding="utf-8")
    return pdf_path, sha, pages

async def render_layout_probe(html: str, settings: dict) -> dict:
    """渲染 HTML 并返回长公式溢出/自动缩放统计（阶段 3 专项测试用，不落盘）。
    返回形如 {"overflow": n, "scaled": n, "unhandled": n}；溢出长公式已被 zoom 缩放适配。"""
    return await asyncio.to_thread(_render_layout_probe_sync, html, settings)


def _render_layout_probe_sync(html: str, settings: dict) -> dict:
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "practice.html").write_text(html, encoding="utf-8")
        shutil.copytree(katex_dist_dir(), root / "katex")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto((root / "practice.html").as_uri(), wait_until="load")
                page.wait_for_function("window.__katexLayout !== undefined", timeout=15000)
                return page.evaluate("window.__katexLayout")
            finally:
                browser.close()
