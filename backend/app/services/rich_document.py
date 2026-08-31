"""阶段 0：旧内容块 → 新富文本文档结构转换器（迁移规则的唯一实现）。

新文档为 Tiptap/ProseMirror 风格 JSON，schema_version=1。节点类型：

    doc            {type, schema_version, content: [块级节点]}
    paragraph      {type, content: [行内节点]}
    text           {type, text, marks?: []}（marks 为阶段 2 预留）
    inlineFormula  {type, attrs: {latex}}          行内公式
    displayFormula {type, attrs: {latex}}          独立公式
    image          {type, attrs: {src, align?, width?}}   块级图片
    inlineImage    {type, attrs: {src}}            选项/段落内行内小图
    optionGroup    {type, content: [option]}       选项组（视觉连续、底层特殊节点）
    option         {type, attrs: {label}, content: [行内节点]}
    answerSpace    {type, attrs: {rows}}           答题留白
    horizontalRule {}                             横线（填写线/分隔线，阶段 2 补充）

迁移规则（旧 → 新）：
    text 块        → 按单个换行拆为 paragraph；段内识别行内图片与公式
    image 块       → image 节点（src 来自 content，align/width 来自 style_config）
    options 块     → optionGroup；选项内图片为 inlineImage
    answer_space 块→ answerSpace（rows 来自 style_config）
    $...$ / \\(...\\)        → inlineFormula；无法解析时保留原文并记录警告
    $$...$$ / \\[...\\]      → displayFormula；同上

幂等性：转换只读取旧字段（块/快照），不修改旧字段；重复执行结果一致。
"""

import json
import re

from app.services import typography

DOC_SCHEMA_VERSION = 1

# 行内图片：Markdown 包装或裸资产引用（与 block_service 的物化规则对应）
_INLINE_IMG_RE = re.compile(r"(!\[[^\]]*\]\()?(asset://[^\s\)]+|/api/practices/[^\s\)]+)(\))?")

# 公式包装：先独立后行内，避免 $$ 被行内规则误匹配
_DISPLAY_FORMULA_RE = re.compile(r"\$\$([^$]+?)\$\$|\\\[(.+?)\\\]", re.S)
_INLINE_FORMULA_RE = re.compile(r"(?<![\d$])\$(?!\$)([^$\n]+?)\$(?!\$)|\\\((.+?)\\\)")


def _balanced_braces(s: str) -> bool:
    return s.count("{") == s.count("}")


def _inline_nodes(text: str, warnings: list[str], context: str) -> list[dict]:
    """把一段文字解析为行内节点序列（图片 → 公式 → 纯文本）。"""
    nodes: list[dict] = []

    def push_text(seg: str):
        if not seg:
            return
        last = 0
        for m in _DISPLAY_FORMULA_RE.finditer(seg):
            pre = seg[last:m.start()]
            _push_text_no_display(pre)
            latex = (m.group(1) or m.group(2) or "").strip()
            if latex and _balanced_braces(latex):
                nodes.append({"type": "displayFormula", "attrs": {"latex": latex}})
            else:
                warnings.append(f"{context}: 独立公式无法解析，保留原文")
                _push_text_no_display(m.group(0))
            last = m.end()
        _push_text_no_display(seg[last:])

    def _push_text_no_display(seg: str):
        """段内行内公式切分（调用前已处理独立公式）。"""
        if not seg:
            return
        last = 0
        for m in _INLINE_FORMULA_RE.finditer(seg):
            nodes.extend(_image_nodes(seg[last:m.start()]))
            latex = (m.group(1) or m.group(2) or "").strip()
            if latex and _balanced_braces(latex):
                nodes.append({"type": "inlineFormula", "attrs": {"latex": latex}})
            else:
                warnings.append(f"{context}: 行内公式无法解析，保留原文")
                nodes.extend(_image_nodes(m.group(0)))
            last = m.end()
        nodes.extend(_image_nodes(seg[last:]))

    push_text(text)
    return _merge_text(nodes)


def _inline_only_nodes(text: str, warnings: list[str], context: str) -> list[dict]:
    """仅行内公式/图片切分（独立公式已在外层提升为块级节点，阶段 3）。"""
    nodes: list[dict] = []
    last = 0
    for m in _INLINE_FORMULA_RE.finditer(text):
        nodes.extend(_image_nodes(text[last:m.start()]))
        latex = (m.group(1) or m.group(2) or "").strip()
        if latex and _balanced_braces(latex):
            nodes.append({"type": "inlineFormula", "attrs": {"latex": latex}})
        else:
            warnings.append(f"{context}: 行内公式无法解析，保留原文")
            nodes.extend(_image_nodes(m.group(0)))
        last = m.end()
    nodes.extend(_image_nodes(text[last:]))
    return _merge_text(nodes)


def _line_nodes(line: str, warnings: list[str], context: str) -> list[dict]:
    """一行文字 → 段落/独立公式节点序列：$$…$$ 提升为顶层 displayFormula（前端为块级节点，
    放段落内会被编辑器丢弃）；前后文字各自成段。"""
    out: list[dict] = []
    last = 0
    for m in _DISPLAY_FORMULA_RE.finditer(line):
        pre = line[last:m.start()]
        if pre.strip():
            out.append({"type": "paragraph", "content": _inline_only_nodes(pre, warnings, context)})
        latex = (m.group(1) or m.group(2) or "").strip()
        if latex and _balanced_braces(latex):
            out.append({"type": "displayFormula", "attrs": {"latex": latex}})
        else:
            warnings.append(f"{context}: 独立公式无法解析，保留原文")
            out.append({"type": "paragraph",
                        "content": _inline_only_nodes(m.group(0), warnings, context)})
        last = m.end()
    tail = line[last:]
    if tail.strip():
        out.append({"type": "paragraph", "content": _inline_only_nodes(tail, warnings, context)})
    if not out:
        out.append({"type": "paragraph", "content": [{"type": "text", "text": ""}]})
    return out


def _image_nodes(text: str) -> list[dict]:
    """切出行内图片引用；其余为纯文本。"""
    nodes: list[dict] = []
    last = 0
    for m in _INLINE_IMG_RE.finditer(text):
        pre = text[last:m.start()]
        if pre.strip():
            nodes.append({"type": "text", "text": pre.strip()})
        elif pre and nodes and nodes[-1]["type"] == "text":
            pass  # 纯空白：丢弃（与旧物化规则的 strip 行为一致）
        nodes.append({"type": "inlineImage", "attrs": {"src": m.group(2)}})
        last = m.end()
    tail = text[last:]
    if tail.strip():
        nodes.append({"type": "text", "text": tail.strip()})
    return nodes


def _merge_text(nodes: list[dict]) -> list[dict]:
    """合并相邻 text 节点，去掉空段。"""
    out: list[dict] = []
    for n in nodes:
        if n["type"] == "text" and not n["text"].strip():
            continue
        if out and out[-1]["type"] == "text" and n["type"] == "text":
            out[-1] = {"type": "text", "text": out[-1]["text"] + n["text"]}
        else:
            out.append(n)
    return out


def _paragraph(content: str, warnings: list[str], context: str) -> dict:
    return {"type": "paragraph",
            "content": _inline_nodes(content, warnings, context) or [{"type": "text", "text": ""}]}


def doc_from_blocks(blocks, warnings: list[str] | None = None) -> dict:
    """按内容块（旧结构真源）生成新文档。blocks 需按 position 排序。"""
    if warnings is None:
        warnings = []
    content: list[dict] = []
    for b in blocks:
        if b.block_type == "text":
            text = b.content or ""
            if not text.strip():
                continue
            for line in text.split("\n"):
                content.extend(_line_nodes(line, warnings, f"text块{b.id}"))
        elif b.block_type == "image":
            m = re.match(r"\s*(asset://[^\s\)]+|/api/practices/[^\s\)]+)", b.content or "")
            if not m:
                warnings.append(f"image块{b.id}: 内容不是资产引用，保留为文字段")
                content.append(_paragraph((b.content or "").strip(), warnings, f"image块{b.id}"))
                continue
            attrs = {"src": m.group(1)}
            style = b.style_config or {}
            if style.get("align"):
                attrs["align"] = style["align"]
            if style.get("width"):
                attrs["width"] = style["width"]
            content.append({"type": "image", "attrs": attrs})
        elif b.block_type == "options":
            try:
                opts = json.loads(b.content) if b.content else []
            except (TypeError, ValueError):
                warnings.append(f"options块{b.id}: JSON 无法解析，保留原文为文字段")
                content.append(_paragraph((b.content or "").strip(), warnings, f"options块{b.id}"))
                continue
            group = []
            for o in opts:
                label = (o or {}).get("label") or "?"
                group.append({
                    "type": "option",
                    "attrs": {"label": label},
                    "content": _inline_nodes((o or {}).get("content") or "", warnings,
                                             f"选项{label}") or [{"type": "text", "text": ""}],
                })
            content.append({"type": "optionGroup", "content": group})
        elif b.block_type == "answer_space":
            rows = (b.style_config or {}).get("rows", 4)
            content.append({"type": "answerSpace", "attrs": {"rows": rows}})
        else:
            # answer / explanation 等当前编辑器不消费的块：保留原文并记录（决策：不迁移进正文）
            warnings.append(f"{b.block_type}块{b.id}: 不迁移进新文档正文")
    return {"type": "doc", "schema_version": DOC_SCHEMA_VERSION, "content": content}


def doc_from_snapshot(content: str | None, options: list | None,
                      warnings: list[str] | None = None) -> dict:
    """无内容块时的回退路径：直接从快照生成（与物化规则相同的切分逻辑）。"""
    if warnings is None:
        warnings = []
    nodes: list[dict] = []
    text = content or ""
    # 剔除 Markdown 图片包装并补分隔符（与 block_service.materialize_blocks 一致）
    text = re.sub(r"!\[[^\]]*\]\((asset://[^\s\)]+)\)", r" \1 ", text)
    last = 0
    asset_re = re.compile(r"asset://[^\s\)]+")
    for m in asset_re.finditer(text):
        pre = text[last:m.start()].strip()
        if pre:
            for line in pre.split("\n"):
                nodes.extend(_line_nodes(line, warnings, "快照"))
        nodes.append({"type": "image", "attrs": {"src": m.group(0), "align": "center",
                                                 "width": "fit"}})
        last = m.end()
    tail = text[last:].strip()
    if tail:
        for line in tail.split("\n"):
            nodes.extend(_line_nodes(line, warnings, "快照"))
    if options:
        group = []
        for o in options:
            label = (o or {}).get("label") or "?"
            group.append({
                "type": "option",
                "attrs": {"label": label},
                "content": _inline_nodes((o or {}).get("content") or "", warnings,
                                         f"选项{label}") or [{"type": "text", "text": ""}],
            })
        nodes.append({"type": "optionGroup", "content": group})
    return {"type": "doc", "schema_version": DOC_SCHEMA_VERSION, "content": nodes}


def add_image_layout_default(doc: dict) -> int:
    """阶段 4：为缺失 layout 的 image 节点补默认 "row"（与后端并排渲染一致）。
    就地修改 doc；返回补全节点数。幂等：已带 layout 的节点不动。"""
    count = 0
    stack = list(doc.get("content") or [])
    while stack:
        n = stack.pop()
        if n.get("type") == "image":
            attrs = n.setdefault("attrs", {})
            if "layout" not in attrs:
                attrs["layout"] = "row"
                count += 1
        children = n.get("content")
        if isinstance(children, list):
            stack.extend(children)
    return count


def serialize(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False)


# ---------------- 阶段 1：编辑器写回方向（校验 + doc → 旧块/快照反向转换） ----------------

_BLOCK_NODE_TYPES = {"paragraph", "image", "optionGroup", "answerSpace", "bulletList", "orderedList",
                     "horizontalRule", "displayFormula"}
_INLINE_NODE_TYPES = {"text", "hardBreak", "inlineImage", "inlineFormula", "displayFormula"}

# 阶段 2 排版：marks 与段落属性白名单（与前端 tiptap 扩展一一对应）
_MARK_TYPES = {"bold", "italic", "underline", "strike", "superscript", "subscript", "textStyle"}
_PARAGRAPH_ATTRS = {"textAlign", "lineHeight", "spaceBefore", "spaceAfter", "firstLineIndent", "indent"}
_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def validate_doc(doc) -> list[str]:
    """校验编辑器提交的文档是否符合 schema v1；返回错误列表（空 = 合法）。"""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["文档必须是 JSON 对象"]
    if doc.get("type") != "doc":
        errors.append("根节点必须是 doc")
    if doc.get("schema_version") != DOC_SCHEMA_VERSION:
        errors.append(f"不支持的 schema_version: {doc.get('schema_version')}")
    content = doc.get("content")
    if not isinstance(content, list):
        return errors + ["doc.content 必须是数组"]
    for i, n in enumerate(content):
        t = n.get("type")
        if t not in _BLOCK_NODE_TYPES:
            errors.append(f"第{i + 1}个块节点类型非法: {t}")
            continue
        if t == "paragraph":
            errors.extend(_check_paragraph_attrs(n.get("attrs"), f"第{i + 1}段"))
            errors.extend(_check_inline(n.get("content"), f"第{i + 1}段"))
        elif t == "image":
            attrs = n.get("attrs") or {}
            if not isinstance(attrs.get("src"), str):
                errors.append(f"第{i + 1}个图片缺 src")
            w = attrs.get("width")
            if w is not None and w != "fit":
                if isinstance(w, (int, float)):
                    if not (5 <= w <= 100):
                        errors.append(f"第{i + 1}个图片 width 非法: {w}")
                elif not (isinstance(w, str) and w.endswith("%")):
                    errors.append(f"第{i + 1}个图片 width 非法: {w}")
        elif t in ("bulletList", "orderedList"):
            for j, item in enumerate(n.get("content") or []):
                if item.get("type") != "listItem":
                    errors.append(f"第{i + 1}个列表第{j + 1}项不是 listItem")
                    continue
                for k, inner in enumerate(item.get("content") or []):
                    if inner.get("type") != "paragraph":
                        errors.append(f"第{i + 1}个列表第{j + 1}项第{k + 1}块不是段落")
                        continue
                    errors.extend(_check_paragraph_attrs(inner.get("attrs"), f"列表项{j + 1}"))
                    errors.extend(_check_inline(inner.get("content"), f"列表项{j + 1}"))
        elif t == "optionGroup":
            for j, o in enumerate(n.get("content") or []):
                if o.get("type") != "option":
                    errors.append(f"选项组第{j + 1}项不是 option 节点")
                    continue
                errors.extend(_check_inline(o.get("content"), f"选项{j + 1}"))
        elif t == "answerSpace":
            rows = (n.get("attrs") or {}).get("rows", 4)
            if not isinstance(rows, int) or rows < 0:
                errors.append(f"第{i + 1}个留白 rows 非法: {rows}")
        elif t == "displayFormula":
            if not isinstance((n.get("attrs") or {}).get("latex"), str):
                errors.append(f"第{i + 1}个独立公式缺 latex")
    return errors


def _check_paragraph_attrs(attrs, context: str) -> list[str]:
    """段落排版属性校验（阶段 2）；无属性 = 跟随练习默认样式。"""
    errors: list[str] = []
    if attrs is None:
        return errors
    if not isinstance(attrs, dict):
        return [f"{context}: attrs 必须是对象"]
    for key, val in attrs.items():
        if val is None:   # 编辑器序列化会带全量属性，null = 未设置
            continue
        if key not in _PARAGRAPH_ATTRS:
            errors.append(f"{context}: 段落属性不支持: {key}")
        elif key == "textAlign" and val not in ("left", "center", "right", "justify"):
            errors.append(f"{context}: textAlign 非法: {val}")
        elif key == "lineHeight" and not (isinstance(val, (int, float)) and 0 < val <= 4):
            errors.append(f"{context}: lineHeight 非法: {val}")
        elif key in ("spaceBefore", "spaceAfter") and not (
                isinstance(val, (int, float)) and 0 <= val <= 72):
            errors.append(f"{context}: {key} 非法: {val}")
        elif key == "indent" and not (isinstance(val, int) and 0 <= val <= 8):
            errors.append(f"{context}: indent 非法: {val}")
    return errors


def _check_marks(marks, context: str) -> list[str]:
    """文字标记白名单校验（阶段 2）。"""
    errors: list[str] = []
    if marks is None:
        return errors
    if not isinstance(marks, list):
        return [f"{context}: marks 必须是数组"]
    for m in marks:
        t = m.get("type")
        if t not in _MARK_TYPES:
            errors.append(f"{context}: 标记类型非法: {t}")
            continue
        if t != "textStyle":
            continue
        for key, val in (m.get("attrs") or {}).items():
            if val is None:   # 未设置的样式属性不算覆盖
                continue
            if key == "fontFamily" and val not in typography.FONT_NAMES:
                errors.append(f"{context}: 字体不在白名单: {val}")
            elif key == "fontSize" and not (
                    isinstance(val, (int, float)) and 4 <= val <= 72):
                errors.append(f"{context}: fontSize 非法: {val}")
            elif key == "color" and not (isinstance(val, str) and _COLOR_RE.match(val)):
                errors.append(f"{context}: color 非法: {val}")
    return errors


def _check_inline(nodes, context: str) -> list[str]:
    """校验行内节点序列；None/缺省按空内容容错（空选项等）。"""
    errors: list[str] = []
    if nodes is None:
        return errors
    if not isinstance(nodes, list):
        return [f"{context}: content 必须是数组"]
    for n in nodes:
        t = n.get("type")
        if t not in _INLINE_NODE_TYPES:
            errors.append(f"{context}: 行内节点类型非法: {t}")
        elif t == "text":
            if not isinstance(n.get("text"), str):
                errors.append(f"{context}: text 节点缺 text")
            else:
                errors.extend(_check_marks(n.get("marks"), context))
        elif t in ("inlineImage",) and not isinstance((n.get("attrs") or {}).get("src"), str):
            errors.append(f"{context}: 行内图片缺 src")
        elif t in ("inlineFormula", "displayFormula") and not isinstance(
                (n.get("attrs") or {}).get("latex"), str):
            errors.append(f"{context}: 公式缺 latex")
    return errors


def _inline_to_markdown(nodes: list) -> str:
    """行内节点序列 → 旧 Markdown 规范文本（图片包装/公式包装与物化规则对应）。"""
    out: list[str] = []
    for n in nodes or []:
        t = n.get("type")
        if t == "text":
            out.append(n.get("text") or "")
        elif t == "hardBreak":
            out.append("\n")   # 选项内换段（阶段 1：Enter 不拆分选项）
        elif t == "inlineImage":
            out.append(f"![图]({(n.get('attrs') or {}).get('src', '')})")
        elif t == "inlineFormula":
            out.append(f"${(n.get('attrs') or {}).get('latex', '')}$")
        elif t == "displayFormula":
            out.append(f"$${(n.get('attrs') or {}).get('latex', '')}$$")
    return "".join(out)


def blocks_from_doc(doc: dict) -> list[dict]:
    """doc → 旧内容块平铺数据 [{block_type, content, style}, …]（阶段 1 反向双写）。
    连续段落合并为一个 text 块（与旧物化粒度一致）；行内公式/行内图回到 Markdown 包装。"""
    blocks: list[dict] = []
    text_lines: list[str] = []

    def flush_text():
        joined = "\n".join(text_lines).strip()
        if joined:
            blocks.append({"block_type": "text", "content": joined, "style": None})
        text_lines.clear()

    for node in doc.get("content") or []:
        t = node.get("type")
        if t == "paragraph":
            text_lines.append(_inline_to_markdown(node.get("content") or []))
        elif t == "image":
            flush_text()
            attrs = node.get("attrs") or {}
            style = {}
            if attrs.get("align"):
                style["align"] = attrs["align"]
            if attrs.get("width"):
                style["width"] = attrs["width"]
            blocks.append({"block_type": "image", "content": attrs.get("src"),
                           "style": style or None})
        elif t == "optionGroup":
            flush_text()
            opts = [{"label": (o.get("attrs") or {}).get("label") or "?",
                     "content": _inline_to_markdown(o.get("content") or [])}
                    for o in node.get("content") or [] if o.get("type") == "option"]
            blocks.append({"block_type": "options",
                           "content": json.dumps(opts, ensure_ascii=False), "style": None})
        elif t == "answerSpace":
            flush_text()
            blocks.append({"block_type": "answer_space", "content": None,
                           "style": {"rows": (node.get("attrs") or {}).get("rows", 4)}})
        elif t == "horizontalRule":
            # 旧块无横线类型：降级为一行下划线（仅用于快照兼容；渲染以 rich_document 为准）
            text_lines.append("＿" * 16)
        elif t in ("bulletList", "orderedList"):
            flush_text()
            text_lines.extend(_list_lines(node))
            flush_text()
        elif t == "displayFormula":
            # 独立公式 → 旧 text 块内独占一行的 $$…$$（回迁幂等）
            text_lines.append(f"$${(node.get('attrs') or {}).get('latex', '')}$$")
    flush_text()
    return blocks


def _list_lines(node: dict, depth: int = 0) -> list[str]:
    """列表 → 平铺文字行（旧块无列表结构；项目符号/编号以文字前缀降级，阶段 2 兼容策略）。"""
    lines: list[str] = []
    ordered = node.get("type") == "orderedList"
    for i, item in enumerate(node.get("content") or []):
        if item.get("type") != "listItem":
            continue
        prefix = "  " * depth + (f"{i + 1}. " if ordered else "• ")
        first = True
        for inner in item.get("content") or []:
            if inner.get("type") == "paragraph":
                line = _inline_to_markdown(inner.get("content") or [])
                lines.append((prefix if first else "  " * (depth + 1)) + line)
                first = False
            elif inner.get("type") in ("bulletList", "orderedList"):
                lines.extend(_list_lines(inner, depth + 1))
    return lines


def sync_rich_document(pq, blocks) -> list[str]:
    """由给定内容块列表重建 rich_document（阶段 0 双写桥；阶段 1 编辑器上线后反转方向）。
    blocks 必须由调用方显式传入（直接查库结果），避免异步上下文懒加载。
    只修改新字段，不触碰旧字段。返回警告列表。"""
    warnings: list[str] = []
    ordered = sorted(blocks or [], key=lambda b: b.position)
    if ordered:
        doc = doc_from_blocks(ordered, warnings)
    else:
        doc = doc_from_snapshot(pq.content_snapshot, pq.options_snapshot, warnings)
    pq.rich_document = serialize(doc)
    pq.doc_version = DOC_SCHEMA_VERSION
    return warnings
