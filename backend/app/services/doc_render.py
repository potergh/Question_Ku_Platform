"""阶段 2：rich_document → 题目 HTML（预览与 PDF 共用管线）。

无排版信息（无 marks、无段落属性）时输出与旧块渲染字节级一致，保证基线样本不漂移；
有排版信息时按白名单令牌生成内联样式（Chromium 渲染 PDF 直接消费）。
"""

import html as _html
import re

from app.services import practice_service, typography

# fit 默认上限：宽不超内容区 50%、高不超 8cm（与旧块渲染及 docx 导出同源）
FIT_STYLE = "max-width:50%;max-height:8cm"

_MARK_TAGS = {"bold": "b", "italic": "i", "underline": "u", "strike": "s",
              "superscript": "sup", "subscript": "sub"}


def _text_html(text: str, plain: bool) -> str:
    """转义；**…** → <b> 仅对无 marks 的 run 生效（兼容旧 Markdown 加粗残留）。"""
    s = _html.escape(text or "")
    if plain:
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return s


def _textstyle_css(attrs: dict) -> str:
    parts: list[str] = []
    if attrs.get("fontFamily"):
        parts.append(f"font-family:{typography.css_font_family(attrs['fontFamily'])}")
    if isinstance(attrs.get("fontSize"), (int, float)):
        parts.append(f"font-size:{attrs['fontSize']:g}pt")
    if attrs.get("color"):
        parts.append(f"color:{attrs['color']}")
    return ";".join(parts)


def _marks_wrap(inner: str, marks) -> str:
    for m in marks or []:
        tag = _MARK_TAGS.get(m.get("type"))
        if tag:
            inner = f"<{tag}>{inner}</{tag}>"
        elif m.get("type") == "textStyle":
            style = _textstyle_css(m.get("attrs") or {})
            if style:
                # 样式值含双引号（font-family 链），写入属性必须转义
                inner = f'<span style="{_html.escape(style, quote=True)}">{inner}</span>'
    return inner


def _asset_uri(src: str, assets) -> str:
    """asset://practice/xxx → 本地文件 URI；其余（/api/…）原样。"""
    if src.startswith("asset://practice/"):
        return (assets / src.removeprefix("asset://practice/")).as_uri()
    return src


def inline_html(nodes, assets) -> str:
    """行内节点序列 → HTML（公式保留 $ 定界符交给 KaTeX 自动渲染）。"""
    out: list[str] = []
    for n in nodes or []:
        t = n.get("type")
        if t == "text":
            marks = n.get("marks")
            out.append(_marks_wrap(_text_html(n.get("text", ""), not marks), marks))
        elif t == "hardBreak":
            out.append("<br>")
        elif t == "inlineImage":
            uri = _asset_uri((n.get("attrs") or {}).get("src", ""), assets)
            out.append(f'<img src="{uri}" style="max-height:3.4em;vertical-align:middle">')
        elif t == "inlineFormula":
            out.append(f"${_html.escape((n.get('attrs') or {}).get('latex', ''))}$")
        elif t == "displayFormula":
            out.append(f"$${_html.escape((n.get('attrs') or {}).get('latex', ''))}$$")
    return "".join(out)


def _paragraph_style(attrs: dict) -> str:
    """段落排版属性 → 内联样式（只输出显式设置项；缺省 = 跟随练习默认）。"""
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


def norm_para_attrs(attrs) -> dict:
    """过滤默认值：ProseMirror 序列化会带上全部属性，等价默认的不算局部覆盖。"""
    out = {}
    for k, v in (attrs or {}).items():
        if v is None or v is False or v == 0 or v == "":
            continue
        if k == "textAlign" and v == "left":
            continue
        out[k] = v
    return out


def _img_html(src: str, attrs: dict, assets) -> str:
    align = attrs.get("align", "center")
    w = attrs.get("width", "fit")
    if not w or w == "fit":
        width_css = FIT_STYLE
    elif isinstance(w, (int, float)):
        width_css = f"width:{w:g}%"
    else:
        width_css = f"width:{w}"
    return (f'<div class="q-img" style="text-align:{align}">'
            f'<img src="{_asset_uri(src, assets)}" style="{width_css};height:auto"></div>')


def _list_html(node: dict, assets) -> str:
    tag = "ol" if node.get("type") == "orderedList" else "ul"
    items: list[str] = []
    for item in node.get("content") or []:
        if item.get("type") != "listItem":
            continue
        segs: list[str] = []
        for inner in item.get("content") or []:
            if inner.get("type") == "paragraph":
                segs.append(inline_html(inner.get("content"), assets))
            elif inner.get("type") in ("bulletList", "orderedList"):
                segs.append(_list_html(inner, assets))
        items.append("<li>" + ("<br>".join(segs) if segs else "") + "</li>")
    return f'<{tag} class="q-list">{"".join(items)}</{tag}>'


def question_html(doc: dict, practice_id: str, prefix: str) -> str:
    """单题文档 → 题目体 HTML；题号/分值并入首个普通段落（与旧渲染同行规则一致）。"""
    assets = practice_service.practice_assets_dir(practice_id)
    out: list[str] = []
    imgs: list[dict] = []
    paras: list[str] = []   # 连续无属性段落缓冲（合并为单个 q-text，字节级对齐旧渲染）
    prefix_used = False

    def flush_paras():
        nonlocal prefix_used
        if not paras:
            return
        body = "<br>".join(paras)
        if not prefix_used:
            out.append(f'<div class="q-text"><b>{_html.escape(prefix)}</b>{body}</div>')
            prefix_used = True
        else:
            out.append(f'<div class="q-text">{body}</div>')
        paras.clear()

    def flush_imgs():
        if not imgs:
            return
        if len(imgs) == 1:
            out.append(_img_html(imgs[0]["src"], imgs[0]["attrs"], assets))
        else:
            def _cell_style(attrs):
                h = (attrs or {}).get("height")
                if isinstance(h, (int, float)) and h > 0:
                    return f"max-width:100%;height:auto;max-height:{h:g}px"
                return "max-width:100%;height:auto"
            cells = "".join(
                f'<div class="q-img-cell"><img src="{_asset_uri(i["src"], assets)}" '
                f'style="{_cell_style(i["attrs"])}"></div>' for i in imgs)
            out.append(f'<div class="q-img-row">{cells}</div>')
        imgs.clear()

    for node in doc.get("content") or []:
        t = node.get("type")
        if t == "paragraph":
            attrs = norm_para_attrs(node.get("attrs"))
            if not attrs:
                paras.append(inline_html(node.get("content"), assets))
                continue
            flush_paras(); flush_imgs()
            style = _paragraph_style(attrs)
            body = inline_html(node.get("content"), assets)
            if not prefix_used:
                out.append(f'<div class="q-text" style="{style}">'
                           f'<b>{_html.escape(prefix)}</b>{body}</div>')
                prefix_used = True
            else:
                out.append(f'<div class="q-text" style="{style}">{body}</div>')
        elif t == "image":
            flush_paras()
            attrs = node.get("attrs") or {}
            if attrs.get("layout") == "block":
                flush_imgs()
                out.append(_img_html(attrs.get("src", ""), attrs, assets))
            else:
                imgs.append({"src": attrs.get("src", ""), "attrs": attrs})
        elif t == "displayFormula":
            flush_paras(); flush_imgs()
            latex = _html.escape((node.get("attrs") or {}).get("latex", ""))
            out.append(f'<div class="q-formula" style="text-align:center;margin:4px 0">$${latex}$$</div>')
        elif t == "optionGroup":
            flush_paras(); flush_imgs()
            rows = "".join(
                f'<div class="q-option"><span class="opt-label">'
                f'{_html.escape((o.get("attrs") or {}).get("label", ""))}.</span>'
                f'{inline_html(o.get("content"), assets)}</div>'
                for o in node.get("content") or [] if o.get("type") == "option")
            out.append(f'<div class="q-options">{rows}</div>')
        elif t == "answerSpace":
            flush_paras(); flush_imgs()
            rows = int((node.get("attrs") or {}).get("rows", 0))
            lines = '<div class="space-line"></div>' * rows
            out.append(f'<div class="answer-space">{lines}</div>')
        elif t == "horizontalRule":
            flush_paras(); flush_imgs()
            out.append('<hr class="q-hr">')
        elif t in ("bulletList", "orderedList"):
            flush_paras(); flush_imgs()
            out.append(_list_html(node, assets))
    flush_paras(); flush_imgs()
    if not prefix_used:   # 无文字内容（纯图片题）：题号单独一行并置顶
        out.insert(0, f'<div class="q-text"><b>{_html.escape(prefix)}</b></div>')
    return "".join(out)
