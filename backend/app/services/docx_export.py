"""Word 导出：练习块 → 可编辑 docx（仅学生版，规格 11.2）。"""

import io
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt

from app.services import practice_service
from app.services.render_service import render_settings

A4_W, A4_H = Cm(21), Cm(29.7)


def build_docx(practice, practice_id: str) -> bytes:
    s = render_settings(practice)
    margin = Cm(float(s["margin"].removesuffix("mm")) / 10)   # mm → cm（Cm() 收厘米）
    content_width = A4_W - 2 * margin

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = A4_W, A4_H
    sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = margin
    if s["show_page_number"]:
        _add_page_number(sec)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(practice.title)
    run.bold = True
    run.font.size = Pt(18)
    _set_cn_font(run)
    if practice.subtitle:
        ps = doc.add_paragraph(practice.subtitle)
        ps.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if s["show_total_score"]:
        total = sum(pq.score or 0 for sec2 in practice.sections for pq in sec2.questions)
        if total > 0:
            pt = doc.add_paragraph(f"满分：{total:g} 分")
            pt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if s["show_info_bar"]:
        doc.add_paragraph("姓名：____________　班级：____________　日期：____________")

    assets = practice_service.practice_assets_dir(practice_id)
    for section in practice.sections:
        if section.start_on_new_page:
            bp = doc.add_paragraph()
            bp.add_run().add_break(WD_BREAK.PAGE)
        if section.show_title:
            sp = doc.add_paragraph()
            sr = sp.add_run(section.title)
            sr.bold = True
            sr.font.size = Pt(13)
            _set_cn_font(sr)
        for pq in section.questions:
            _add_question(doc, pq, assets, content_width, s)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _set_cn_font(run, name="宋体"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


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


def _add_question(doc, pq, assets: Path, content_width, s: dict):
    score_txt = f"（{pq.score:g} 分）" if (s["show_score"] and pq.score is not None) else ""
    doc.add_paragraph(f"{pq.question_number}. {score_txt}".strip())
    for b in pq.blocks:
        style = b.style_config or {}
        if b.block_type == "text":
            # LaTeX 原样保留：Word 可继续编辑（规格 10.2），仅去除 Markdown 加粗标记
            tp = doc.add_paragraph()
            tp.add_run((b.content or "").replace("**", ""))
        elif b.block_type == "image":
            _add_image_block(doc, b, assets, content_width)
        elif b.block_type == "options":
            try:
                opts = json.loads(b.content) if b.content else []
            except (TypeError, json.JSONDecodeError):
                opts = []
            for o in opts:
                op = doc.add_paragraph()
                op.paragraph_format.left_indent = Cm(0.74)
                op.add_run(f"{o.get('label', '')}. {o.get('content', '')}")
        elif b.block_type == "answer_space":
            for _ in range(int(style.get("rows", 0))):
                doc.add_paragraph("")
        # answer/explanation 块学生版不输出


def _add_image_block(doc, b, assets: Path, content_width):
    name = (b.content or "").removeprefix("asset://practice/")
    path = assets / name
    style = b.style_config or {}
    ip = doc.add_paragraph()
    align = style.get("align", "center")
    ip.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT}.get(
        align, WD_ALIGN_PARAGRAPH.CENTER)
    if not path.exists():
        ip.add_run(f"[图片缺失：{name}]")
        return
    width = None
    w = style.get("width", "fit")
    if isinstance(w, str) and w.endswith("%"):
        width = content_width * float(w.removesuffix("%")) / 100
    run = ip.add_run()
    run.add_picture(_picture_source(path), width=width)
    # fit：python-docx 用图片原尺寸；超宽由 Word 内人工调整（V1 可接受）


def _picture_source(path: Path):
    """docx 只识别常见光栅格式；webp/avif 等（OCR 常见）先用 PIL 转 PNG 流。"""
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".ico"}:
        return str(path)
    from PIL import Image
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
