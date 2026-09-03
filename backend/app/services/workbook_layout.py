# -*- coding: utf-8 -*-
"""阶段 5：整册编排布局服务（架构 A：layout_document 与旧 sections 并存）。

布局文档 = 线性块序列（整册渲染/导出/顺序的真源）：
  subtitle      小标题/小节  {type, id, section_id?, title, show_title, start_on_new_page, section_type?}
  question_ref  题目引用      {type, id, question_id}
  custom_text   说明/自定义  {type, id, html, align?}    # 简单富文本（净化后 HTML，图片用 asset://practice/..）
  spacer        空白          {type, id, height}
  page_break    分页符        {type, id}

树状呈现：subtitle 块开启一个新小节分支，其后块归属该小节直到下一个 subtitle。
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.practice import Practice, PracticeQuestion, PracticeSection

BLOCK_TYPES = {"subtitle", "question_ref", "custom_text", "spacer", "page_break"}

# 小标题序号：一、二、三…（超过十个回退为阿拉伯数字）
CN_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]

# 自定义内容富文本白名单标签
_ALLOWED_TAGS = {"p", "div", "br", "strong", "b", "em", "i", "u", "span",
                 "img", "h1", "h2", "h3", "ol", "ul", "li"}
_TAG_FULL_RE = re.compile(r"<(/)?([a-zA-Z][a-zA-Z0-9]*)((?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*=(?:\"[^\"]*\"|'[^']*'|[^\s>]+))*)\s*/?>")
_ASSET_SRC_RE = re.compile(r'src="asset://practice/([^"]+)"')


# 自定义内容允许保留的内联 CSS 属性（白名单，防注入）
_CSS_ALLOWED = {"font-family", "font-size", "color", "line-height",
                "margin-top", "margin-bottom", "margin-left", "text-indent", "text-align"}


def _clean_css_style(raw: str) -> str:
    out = []
    for decl in (raw or "").split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop = prop.strip().lower()
        val = val.strip()
        if not prop or not val or prop not in _CSS_ALLOWED:
            continue
        low = val.lower()
        if "url(" in low or "expression(" in low or "javascript" in low:
            continue
        out.append(f"{prop}: {val}")
    return "; ".join(out)


def sanitize_custom_html(html: str) -> str:
    """轻量净化自定义内容 HTML：去 script/style/iframe、事件属性、javascript:；
    仅保留白名单标签与 img 的 src 属性。"""
    if not html:
        return ""
    s = re.sub(r"<\s*(script|style|iframe|object|embed)\b[^>]*>.*?</\s*\1\s*>",
               "", html, flags=re.S | re.I)
    s = re.sub(r"\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", s, flags=re.I)
    s = re.sub(r"javascript:", "", s, flags=re.I)

    def repl(m):
        closing, name, attrs = m.group(1), (m.group(2) or "").lower(), m.group(3) or ""
        if name not in _ALLOWED_TAGS:
            return "</span>" if closing else "<span>"
        keep = ""
        if name == "img":
            for am in re.finditer(r'src=("[^"]*"|\'[^\']*\')', attrs, flags=re.I):
                keep += f" src={am.group(1)}"
        sm = re.search(r'style="([^"]*)"', attrs, flags=re.I)
        if sm:
            clean = _clean_css_style(sm.group(1))
            if clean:
                keep += f' style="{clean}"'
        return f"</{name}>" if closing else f"<{name}{keep}>"

    return _TAG_FULL_RE.sub(repl, s)


def resolve_custom_asset_srcs(html: str, practice_id: str,
                              resolver) -> str:
    """把自定义内容里的 asset://practice/.. 图片引用替换为可渲染 src（resolver 接收文件名返回 src）。"""
    if not html:
        return html
    return _ASSET_SRC_RE.sub(lambda m: f'src="{resolver(m.group(1))}"', html)


def section_label(index: int) -> str:
    return CN_NUM[index - 1] if 0 < index <= len(CN_NUM) else str(index)


def build_layout_from_sections(practice: Practice) -> list[dict]:
    """旧 sections → 布局块序列（subtitle 携带 section_id 以便复用同步）。"""
    blocks: list[dict] = []
    for sec in practice.sections:
        blocks.append({
            "type": "subtitle", "id": f"sub_{sec.id}", "section_id": sec.id,
            "title": sec.title, "show_title": sec.show_title,
            "start_on_new_page": sec.start_on_new_page,
            "section_type": sec.section_type,
        })
        for q in sec.questions:
            blocks.append({"type": "question_ref", "id": f"qr_{q.id}", "question_id": q.id})
    return blocks


async def ensure_layout(db, practice: Practice) -> list[dict]:
    """惰性迁移：layout_document 为空时由 sections 构建并持久化。返回布局列表。"""
    if practice.layout_document:
        return practice.layout_document
    layout = build_layout_from_sections(practice)
    practice.layout_document = layout
    await db.flush()
    return layout


async def append_questions_to_layout(db, practice: Practice, added_pqs: list) -> None:
    """向整册布局追加新加入的题目（question_ref），保证整册编排/导出能显示新题。

    - layout_document 为空 → 按数据库最新 sections（含新题）重建
    - 已存在 → 校验规整后，把新题插入其所属小节（无小节则新建 subtitle），
      保证整册画布与练习结构一致（不会因追加到全局末尾而错挂到错误小节）。
    """
    if not added_pqs:
        return
    if practice.layout_document:
        layout = validate_layout(practice.layout_document)
    else:
        # 从数据库重建：不依赖传入 practice 对象的集合（可能因 commit 过期）
        sections = (await db.execute(
            select(PracticeSection)
            .where(PracticeSection.practice_id == practice.id)
            .options(selectinload(PracticeSection.questions))
            .order_by(PracticeSection.position)
        )).scalars().all()
        layout = []
        for sec in sections:
            layout.append({
                "type": "subtitle", "id": f"sub_{sec.id}", "section_id": sec.id,
                "title": sec.title, "show_title": sec.show_title,
                "start_on_new_page": sec.start_on_new_page,
                "section_type": sec.section_type,
            })
            for q in sec.questions:
                layout.append({"type": "question_ref", "id": f"qr_{q.id}", "question_id": q.id})
    existing_qids = {b.get("question_id") for b in layout if b.get("type") == "question_ref"}
    # 新题 -> 所属小节（供定位/新建 subtitle）
    sec_info = {}
    for pq in added_pqs:
        if pq.id in existing_qids:
            continue
        r = await db.execute(select(PracticeSection).where(PracticeSection.id == pq.section_id))
        sec = r.scalar_one_or_none()
        if sec:
            sec_info[pq.id] = sec
    # section_id -> subtitle 所在 layout 下标
    def _sub_index():
        return {b.get("section_id"): i for i, b in enumerate(layout) if b.get("type") == "subtitle" and b.get("section_id")}
    sub_index = _sub_index()
    for pq in added_pqs:
        if pq.id in existing_qids:
            continue
        blk = {"type": "question_ref", "id": f"qr_{pq.id}", "question_id": pq.id}
        sec = sec_info.get(pq.id)
        if sec is None:
            layout.append(blk)
            continue
        if sec.id in sub_index:
            # 所属小节已存在：插到该小节内最后一个题目之后（下一个 subtitle 之前）
            start = sub_index[sec.id]
            end = len(layout)
            for i in range(start + 1, len(layout)):
                if layout[i].get("type") == "subtitle":
                    end = i
                    break
            layout.insert(end, blk)
            sub_index = _sub_index()  # 插入使后续下标偏移，重算
        else:
            # 无对应小节：新建 subtitle + question_ref（追加末尾，可在整册里拖动归位）
            layout.append({
                "type": "subtitle", "id": f"sub_{sec.id}", "section_id": sec.id,
                "title": sec.title, "show_title": sec.show_title,
                "start_on_new_page": sec.start_on_new_page,
                "section_type": sec.section_type,
            })
            layout.append(blk)
            sub_index = _sub_index()
    practice.layout_document = layout
    await db.flush()


def validate_layout(layout) -> list[dict]:
    """校验并规整布局块：仅允许已知类型，丢弃非法块。"""
    if not isinstance(layout, list):
        return []
    out: list[dict] = []
    for blk in layout:
        if not isinstance(blk, dict):
            continue
        t = blk.get("type")
        if t not in BLOCK_TYPES:
            continue
        b = {"type": t, "id": blk.get("id") or f"{t}_{len(out)}"}
        if t == "subtitle":
            b.update({
                "title": str(blk.get("title") or "小节"),
                "show_title": bool(blk.get("show_title", True)),
                "start_on_new_page": bool(blk.get("start_on_new_page", False)),
            })
            if blk.get("section_id"):
                b["section_id"] = str(blk["section_id"])
            if blk.get("section_type"):
                b["section_type"] = str(blk["section_type"])
        elif t == "question_ref":
            b["question_id"] = str(blk.get("question_id") or "")
        elif t == "custom_text":
            b["html"] = str(blk.get("html") or "")
            if blk.get("align"):
                b["align"] = str(blk["align"])
        elif t == "spacer":
            h = blk.get("height")
            b["height"] = int(h) if isinstance(h, (int, float)) and h > 0 else 20
        out.append(b)
    return out


async def sync_sections_from_layout(db, practice: Practice, layout: list[dict]) -> list[dict]:
    """布局保存后同步 sections/question 表，使单题模式与旧特性保持一致。

    - subtitle 块 → PracticeSection：带 section_id 复用，否则新建并回写 section_id
    - 更新小节 title/show_title/start_on_new_page；题目按布局重排归属与题号（整册连续）
    - 不删除题目/小节（删除由前端显式确认后调用专用接口）
    返回规整后的布局（含新建小节的 section_id）。
    """
    layout = validate_layout(layout)
    existing = {s.id: s for s in practice.sections}
    qmap = {pq.id: pq for s in practice.sections for pq in s.questions}
    cur_section: PracticeSection | None = None
    q_no = 0
    per_pos: dict[str, int] = {}
    question_refs = []

    for blk in layout:
        t = blk.get("type")
        if t == "subtitle":
            sid = blk.get("section_id")
            sec = existing.get(sid) if sid else None
            if sec is None:
                sec = PracticeSection(
                    practice_id=practice.id,
                    title=blk.get("title") or "小节",
                    section_type=blk.get("section_type") or "custom",
                    position=len(practice.sections),
                )
                practice.sections.append(sec)
                existing[sec.id] = sec
                blk["section_id"] = sec.id
            sec.title = blk.get("title") or sec.title
            sec.show_title = bool(blk.get("show_title", True))
            sec.start_on_new_page = bool(blk.get("start_on_new_page", False))
            if blk.get("section_type"):
                sec.section_type = str(blk["section_type"])
            cur_section = sec
        elif t == "question_ref":
            qid = blk.get("question_id")
            pq = qmap.get(qid)
            if pq is None:
                continue
            if cur_section is None:
                # 题目出现在任何小节之前：归入首个（或新建"未分组"）小节
                if practice.sections:
                    cur_section = practice.sections[0]
                else:
                    cur_section = PracticeSection(
                        practice_id=practice.id, title="未分组", section_type="custom",
                        position=0)
                    practice.sections.append(cur_section)
                    existing[cur_section.id] = cur_section
            if pq.section_id != cur_section.id:
                # 从原小节（已加载集合）移除后挂到新小节；避免 async 下懒加载
                old_sec = existing.get(pq.section_id)
                if old_sec is not None and pq in old_sec.questions:
                    old_sec.questions.remove(pq)
                pq.section_id = cur_section.id
                cur_section.questions.append(pq)
            per_pos[cur_section.id] = per_pos.get(cur_section.id, 0) + 1
            pq.position = per_pos[cur_section.id]
            q_no += 1
            pq.question_number = q_no
            question_refs.append(blk)

    # 归位：各小节内按 position 排序后重新连续编号（布局顺序即最终顺序）
    for sec in practice.sections:
        sec.questions.sort(key=lambda pq: pq.position if pq.position is not None else 10 ** 9)
        for i, pq in enumerate(sec.questions, 1):
            pq.position = i

    await db.flush()
    return layout


async def load_question_map(practice: Practice) -> dict[str, PracticeQuestion]:
    return {pq.id: pq for s in practice.sections for pq in s.questions}
