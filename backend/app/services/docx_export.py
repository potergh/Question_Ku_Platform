"""Word 导出：练习块 → 可编辑 docx（仅学生版，规格 11.2）。"""

import io
import json
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt

from app.services import practice_service
from app.services.render_service import render_settings

A4_W, A4_H = Cm(21), Cm(29.7)
MAX_IMG_H = Cm(24)       # 竖长图高度硬封顶（A4 内容区约 24.7cm）
FIT_MAX_H = Cm(8)        # fit 默认上限：与预览同源，避免图片普遍偏大/忽大忽小


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
    prefix = f"{pq.question_number}. "
    if s["show_score"] and pq.score is not None:
        prefix += f"（{pq.score:g} 分）"
    blocks = sorted(pq.blocks, key=lambda b: b.position)
    # 无文字块（纯图片题）：题号单独一行并置顶；否则并入首个文字段（题号与题干同行）
    prefix_used = not any(b.block_type == "text" for b in blocks)
    if prefix_used:
        doc.add_paragraph(prefix)
    imgs: list = []

    def flush_imgs():
        if not imgs:
            return
        if len(imgs) == 1:
            _add_image_block(doc, imgs[0], assets, content_width)
        else:
            _add_image_row(doc, imgs, assets, content_width)
        imgs.clear()

    for b in blocks:
        if b.block_type == "image":
            imgs.append(b)
            continue
        flush_imgs()
        style = b.style_config or {}
        if b.block_type == "text":
            # LaTeX 原样保留：Word 可继续编辑（规格 10.2），仅去除 Markdown 加粗标记
            tp = doc.add_paragraph()
            tp.add_run(("" if prefix_used else prefix)
                       + (b.content or "").replace("**", ""))
            prefix_used = True
        elif b.block_type == "options":
            try:
                opts = json.loads(b.content) if b.content else []
            except (TypeError, json.JSONDecodeError):
                opts = []
            for o in opts:
                op = doc.add_paragraph()
                op.paragraph_format.left_indent = Cm(0.74)
                op.add_run(f"{o.get('label', '')}. ")
                _add_rich_runs(op, o.get("content", ""), assets)
        elif b.block_type == "answer_space":
            for _ in range(int(style.get("rows", 0))):
                doc.add_paragraph("")
        # answer/explanation 块学生版不输出
    flush_imgs()


def _add_rich_runs(paragraph, content: str, assets: Path):
    """选项文字中的图片引用 → 行内图片（随文字基线排版）。"""
    last = 0
    for m in re.finditer(r"!\[[^\]]*\]\((asset://[^\s\)]+)\)|(asset://[^\s\)]+)", content or ""):
        if m.start() > last:
            paragraph.add_run(content[last:m.start()])
        name = (m.group(1) or m.group(2)).removeprefix("asset://practice/")
        path = assets / name
        if path.exists():
            paragraph.add_run().add_picture(_picture_source(path), height=Cm(0.9))
        else:
            paragraph.add_run(f"[图缺失:{name}]")
        last = m.end()
    if last < len(content or ""):
        paragraph.add_run(content[last:])


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
    if width is None:   # fit：原尺寸，受默认上限（内容区 50% 宽 / 8cm 高）与硬封顶约束
        width = _fit_width(path, content_width)
    run = ip.add_run()
    run.add_picture(_picture_source(path), width=width)


def _add_image_row(doc, imgs, assets: Path, content_width):
    """连续图片并排：无边框单行表格，等宽列；单元格内居中且不超过列宽。"""
    n = len(imgs)
    table = doc.add_table(rows=1, cols=n)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell_w = content_width // n
    for i, b in enumerate(imgs):
        cell = table.rows[0].cells[i]
        cell.width = cell_w
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        name = (b.content or "").removeprefix("asset://practice/")
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


def _fit_width(path: Path, max_width):
    """fit：宽受 max_width 与默认上限（内容区 50%）双重封顶，高度封顶后再反推宽度；读不到尺寸保持原样。"""
    ns = _natural_size(path)
    if not ns:
        return None
    w, h = ns
    cap_w = min(max_width, int(max_width / 2))
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
