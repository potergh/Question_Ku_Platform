"""Render service — 练习块 → 独立 HTML（供 Playwright 出 PDF）。"""

import asyncio
import hashlib
import html as _html
import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from app.models.practice import Practice
from app.services import practice_service, render_ir, typography

MARGIN_PRESETS = {"narrow": "15mm", "normal": "25mm", "wide": "32mm"}
MARGIN_PRESET_MM = {"narrow": 15.0, "normal": 25.0, "wide": 32.0}

PAGE_FOOTER = ('<div style="width:100%;text-align:center;font-size:8px;color:#555;">'
               '第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</div>')


class RenderUnavailable(RuntimeError):
    """渲染依赖不可用（KaTeX 或 Chromium 没装好），且知道该让用户执行什么。

    必须和「渲染过程中内容出错」区分开：前者是环境没配好，提示要直接指到
    ``npm install`` / ``playwright install``；后者才是内容问题。混成一个裸 500，
    部署环境上的表现就是「预览一直不出来」，既看不出缺什么、也看不出该装什么
    （实测 Cloud Studio 沙箱正是这样：Chromium 没装、katex 目录也没带过去）。
    """


def katex_dist_dir() -> Path:
    """frontend/node_modules/katex/dist（渲染时整目录拷入临时渲染目录）。"""
    d = Path(__file__).resolve().parents[3] / "frontend" / "node_modules" / "katex" / "dist"
    if not d.exists():
        raise RenderUnavailable(
            "KaTeX 未安装：找不到 frontend/node_modules/katex/dist，"
            "请先在 frontend/ 执行 npm install"
        )
    return d


def _page_margins(cfg: dict) -> tuple[float, float, float, float]:
    """返回 (top, bottom, left, right) mm。margin_preset=custom 时用自定义各边。"""
    preset = cfg.get("margin_preset", "normal")
    if preset == "custom":
        m = cfg.get("margins") or {}
        return (float(m.get("top", 25)), float(m.get("bottom", 25)),
                float(m.get("left", 25)), float(m.get("right", 25)))
    mm = MARGIN_PRESET_MM.get(preset, 25.0)
    return (mm, mm, mm, mm)


def _resolve_page_vars(text: str, practice: Practice, variables: dict) -> str:
    """替换 {title}/{subject}/{grade}/{date}/{school}/{teacher}；{page}/{total} 保留占位。
    date 用渲染当天（导出日期，用户决策 A）。"""
    if not text:
        return text
    d = {
        "title": practice.title or "",
        "subject": practice.subject or "",
        "grade": practice.grade or "",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "school": (variables or {}).get("school") or "",
        "teacher": (variables or {}).get("teacher") or "",
    }
    out = text
    for k, v in d.items():
        out = out.replace("{" + k + "}", _html.escape(str(v)))
    return out


def render_settings(practice: Practice) -> dict:
    """page_config → 渲染设置（含默认值）。

    阶段 6：新增 orientation / margins(自定义各边) / header / footer / variables。
    兼容旧练习：page_config 无 header 键 → header.enabled=False（不显示页眉）；
    page_config 无 footer 键 → footer=None（沿用旧 show_page_number 页码行为）。
    """
    cfg = practice.page_config or {}
    t, b, l, r = _page_margins(cfg)
    variables = {"school": "", "teacher": "", **(cfg.get("variables") or {})}
    if "header" in cfg:
        header = {**practice_service.DEFAULT_HEADER, **(cfg.get("header") or {})}
    else:
        header = {"enabled": False, "left": "", "center": "", "right": "",
                  "font_size": 9, "distance": 8, "line": False,
                  "first_page_different": False, "first_hidden": False}
    footer = None
    if "footer" in cfg:
        footer = {**practice_service.DEFAULT_FOOTER, **(cfg.get("footer") or {})}
    # 练习级变量解析到各栏文本（{page}/{total} 保留占位由 PDF/Word 各自处理）
    for zone in (header, footer):
        if not zone:
            continue
        for key in ("left", "center", "right"):
            zone[key] = _resolve_page_vars(zone.get(key, ""), practice, variables)
    return {
        "margin": MARGIN_PRESETS.get(cfg.get("margin_preset", "normal"), "25mm"),
        "margin_preset": cfg.get("margin_preset", "normal"),
        "margins": {"top": t, "bottom": b, "left": l, "right": r},
        "orientation": cfg.get("orientation", "portrait"),
        "show_info_bar": cfg.get("show_info_bar", True),
        "info_bar_align": cfg.get("info_bar_align", "left"),
        "show_page_number": cfg.get("show_page_number", True),
        "show_score": cfg.get("show_score", False),
        "show_total_score": cfg.get("show_total_score", False),
        "default_style": typography.practice_default_style(practice),   # 阶段 2 全局默认样式
        "variables": variables,
        "header": header,
        "footer": footer,
    }


def build_practice_html(practice: Practice, practice_id: str) -> str:
    """练习 → 独立 HTML：统一中间结构（render_ir）→ HTML → KaTeX 标签。

    F07 Task 7.8：结构判断（题号并入首段、连续图片并排、段落合并、整册小节
    序号、页头顺序）全部在 `render_ir`，本函数只负责页壳、CSS 与 KaTeX 注入，
    与 Word 导出（`docx_export`）读取同一份 IR，不再各自推断题目结构。
    """
    s = render_settings(practice)
    blocks = render_ir.build_practice_ir(practice, practice_id, s)
    return (_head_css(s["default_style"]) + '<body>'
            + render_ir.blocks_html(blocks, practice_id)
            + _katex_tags() + '</body></html>')


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
    （Windows + --reload 下 uvicorn 0.52 默认 SelectorEventLoop 不支持 asyncio 子进程）

    依赖缺失一律转成 ``RenderUnavailable``，并带上"该执行哪条命令"。
    不这么做的话，缺 Chromium 会以 Playwright 原始异常一路冒泡成 HTTP 500，
    与"内容渲染失败"长得一模一样 —— 调用方（含前端）无法区分，也就没法提示。
    """
    try:
        return await asyncio.to_thread(_render_pdf_bytes_sync, html, settings)
    except RenderUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — 目的就是把底层文案翻成人话
        message = str(exc)
        # Playwright 缺浏览器时的原文：
        #   Executable doesn't exist at ... Please run the following command to
        #   download a new browser version: playwright install
        if "Executable doesn't exist" in message or "playwright install" in message:
            raise RenderUnavailable(
                "Chromium 未安装，无法渲染 PDF 预览与导出。"
                "请在后端虚拟环境里执行：python -m playwright install chromium"
            ) from exc
        raise


def _hf_frag(text: str) -> str:
    """页眉/页脚栏文本 → HTML 片段：普通文本转义，{page}/{total} → Playwright span。"""
    if not text:
        return ""
    out: list[str] = []
    for part in re.split(r"(\{page\}|\{total\})", text):
        if part == "{page}":
            out.append('<span class="pageNumber"></span>')
        elif part == "{total}":
            out.append('<span class="totalPages"></span>')
        else:
            out.append(_html.escape(part))
    return "".join(out)


def _hf_template(zone: dict, top: bool) -> str:
    """Playwright header/footer 模板：三栏（左/中/右）+ 可选分隔线。"""
    fs = int(zone.get("font_size", 9))
    # 页眉/页脚是中文文本，走与正文一致的中文字体（缺 Noto Sans SC 时按系统栈回退）
    style = (f"width:100%;font-size:{fs}px;color:#000;line-height:1.4;"
             f"box-sizing:border-box;font-family:'Noto Sans SC','Microsoft YaHei',Arial,sans-serif;")
    if zone.get("line"):
        style += ("border-bottom:1px solid #999;" if top else "border-top:1px solid #999;")
    cells = "".join(
        f'<div style="flex:1;text-align:{al};overflow:hidden;">{_hf_frag(zone.get(key, ""))}</div>'
        for al, key in (("left", "left"), ("center", "center"), ("right", "right")))
    return (f'<div style="{style}display:flex;justify-content:space-between;align-items:center;">'
            f"{cells}</div>")


def _strip_first_page_zone(pdf_bytes: bytes, top: bool, h_mm: float) -> bytes:
    """用 pymupdf 把第一页顶部/底部页眉页脚区域覆盖为白色（实现“首页不同”）。"""
    import io
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pt = h_mm * 72 / 25.4
    if top:
        rect = pymupdf.Rect(0, 0, page.rect.width, pt)
    else:
        rect = pymupdf.Rect(0, page.rect.height - pt, page.rect.width, page.rect.height)
    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
    out = io.BytesIO()
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    return out.getvalue()


def _render_pdf_bytes_sync(html: str, settings: dict) -> bytes:
    """临时目录内 practice.html + katex/ 子目录，file:// 加载（离线可用）。

    阶段 6：支持纸张方向、自定义页边距、页眉/页脚三栏模板、首页不同。
    """
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
                margins = settings["margins"]
                orientation = settings.get("orientation", "portrait")
                header = settings.get("header")
                footer = settings.get("footer")
                # footer 为 None → 沿用旧 show_page_number 行为（保持旧练习输出不变）
                footer_old = footer is None and settings.get("show_page_number", True)
                show_hf = bool(header and header.get("enabled")) or footer_old or bool(footer and footer.get("enabled"))
                header_tpl = "<div></div>"
                footer_tpl = "<div></div>"
                if header and header.get("enabled"):
                    header_tpl = _hf_template(header, top=True)
                if footer_old:
                    footer_tpl = PAGE_FOOTER
                elif footer and footer.get("enabled"):
                    footer_tpl = _hf_template(footer, top=False)
                mm = lambda v: f"{v}mm"
                pdf = page.pdf(
                    format="A4", print_background=True,
                    landscape=(orientation == "landscape"),
                    margin={"top": mm(margins["top"]), "bottom": mm(margins["bottom"]),
                            "left": mm(margins["left"]), "right": mm(margins["right"])},
                    display_header_footer=show_hf,
                    header_template=header_tpl, footer_template=footer_tpl,
                )
                # 首页不同：pymupdf 覆盖第一页页眉/页脚区域为白色
                if header and header.get("enabled") and header.get("first_page_different") and header.get("first_hidden"):
                    pdf = _strip_first_page_zone(pdf, top=True, h_mm=margins["top"])
                if footer and footer.get("enabled") and footer.get("first_hidden"):
                    pdf = _strip_first_page_zone(pdf, top=False, h_mm=margins["bottom"])
                return pdf
            finally:
                browser.close()


def _preview_cache_key(html: str, settings: dict) -> str:
    """预览 PDF 缓存键：html + 页面临（方向/边距/页眉页脚），改设置即失效。"""
    def zone(z):
        if not z:
            return None
        return {k: z.get(k) for k in ("enabled", "left", "center", "right",
                                      "font_size", "distance", "line",
                                      "first_page_different", "first_hidden")}
    page_key = {
        "orientation": settings.get("orientation"),
        "margins": settings.get("margins"),
        "margin_preset": settings.get("margin_preset"),
        "header": zone(settings.get("header")),
        "footer": zone(settings.get("footer")),
    }
    return hashlib.sha1((html + json.dumps(page_key, ensure_ascii=False)).encode("utf-8")).hexdigest()


async def ensure_preview_pdf(practice_id: str, html: str, settings: dict) -> tuple[Path, str, int]:
    """缓存预览 PDF；sha 命中则跳过浏览器。返回 (路径, sha, 页数)。"""
    from app.services.preview_service import pdf_page_count
    sha = _preview_cache_key(html, settings)
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
