"""Render service — 练习块 → 独立 HTML（供 Playwright 出 PDF）。"""

import html as _html
import json
import re
from pathlib import Path

from app.models.practice import Practice
from app.services import practice_service

MARGIN_PRESETS = {"narrow": "15mm", "normal": "25mm", "wide": "32mm"}


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
    }


def _text_to_html(text: str) -> str:
    """Markdown-lite：转义后处理加粗/换行；LaTeX 定界符原样保留交给 KaTeX。"""
    s = _html.escape(text or "")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = s.replace("\n", "<br>")
    return s


def _block_html(b, practice_id: str) -> str:
    style = b.style_config or {}
    if b.block_type == "text":
        return f'<div class="q-text">{_text_to_html(b.content)}</div>'
    if b.block_type == "image":
        name = (b.content or "").removeprefix("asset://practice/")
        src = (practice_service.practice_assets_dir(practice_id) / name).as_uri()
        align = style.get("align", "center")
        w = style.get("width", "fit")
        width_css = "max-width:100%" if w == "fit" else f"width:{w}"
        return (f'<div class="q-img" style="text-align:{align}">'
                f'<img src="{src}" style="{width_css};height:auto"></div>')
    if b.block_type == "options":
        try:
            opts = json.loads(b.content) if b.content else []
        except (TypeError, json.JSONDecodeError):
            opts = []
        rows = "".join(
            f'<div class="q-option"><span class="opt-label">{_html.escape(o.get("label", ""))}.</span>'
            f'{_text_to_html(o.get("content", ""))}</div>' for o in opts)
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

    body = _section_bodies(practice, s)
    return _head_css() + '<body>' + "".join(head + body) + _katex_tags() + '</body></html>'


def _section_bodies(practice: Practice, s: dict) -> list[str]:
    out: list[str] = []
    for section in practice.sections:
        if section.start_on_new_page:
            out.append('<div class="new-page"></div>')
        if section.show_title:
            out.append(f'<div class="section-title">{_html.escape(section.title)}</div>')
        for pq in section.questions:
            blocks_html = "".join(_block_html(b, practice.id) for b in pq.blocks)
            score_txt = ""
            if s["show_score"] and pq.score is not None:
                score_txt = f'<span class="q-score">（{pq.score:g} 分）</span>'
            out.append(f'<div class="question">'
                       f'<div class="q-head">{pq.question_number}. {score_txt}</div>'
                       f'{blocks_html}</div>')
    return out


def _head_css() -> str:
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>'
            'body { font-family: "SimSun", "Microsoft YaHei", serif; font-size: 10.5pt;'
            ' line-height: 1.7; color: #000; margin: 0; }'
            '.p-title { text-align: center; font-size: 18pt; font-weight: bold; margin-bottom: 4px; }'
            '.p-subtitle { text-align: center; font-size: 12pt; color: #333; margin-bottom: 8px; }'
            '.p-total { text-align: center; font-size: 10.5pt; margin-bottom: 6px; }'
            '.info-bar { margin: 8px 0 14px; font-size: 10.5pt; }'
            '.section-title { font-weight: bold; font-size: 12pt; margin: 14px 0 8px; }'
            '.new-page { page-break-before: always; }'
            '.question { margin-bottom: 12px; }'
            '.q-text { margin: 2px 0; }'
            '.q-img img { max-height: 420px; }'
            '.q-options { margin: 4px 0 4px 2em; }'
            '.q-option { margin: 1px 0; }'
            '.opt-label { margin-right: 4px; }'
            '.q-score { font-size: 9pt; }'
            '.answer-space { margin: 4px 0; }'
            '.space-line { height: 1.9em; border-bottom: 1px solid #999; }'
            '</style></head>')


def _katex_tags() -> str:
    return ('<link rel="stylesheet" href="katex/katex.min.css">'
            '<script defer src="katex/katex.min.js"></script>'
            '<script defer src="katex/contrib/auto-render.min.js"></script>'
            '<script>window.addEventListener("DOMContentLoaded", function(){'
            'renderMathInElement(document.body, {delimiters:['
            '{left:"$$",right:"$$",display:true},{left:"\\\\[",right:"\\\\]",display:true},'
            '{left:"$",right:"$",display:false},{left:"\\\\(",right:"\\\\)",display:false}]});'
            'window.__katexDone = true;});</script>')
