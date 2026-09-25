"""兼容层：`rich_document` → 题目 HTML 的旧入口。

F07 Task 7.8 起，结构推断与 HTML 投影统一由 `render_ir`（统一渲染适配层）实现，
本模块只保留对外签名（`question_html` / `norm_para_attrs`），避免调用方改动。
新代码请直接用 `app.services.render_ir`。
"""

from app.services.render_ir import (  # noqa: F401  —— 兼容再导出
    FIT_STYLE,
    norm_para_attrs,
    question_html_from_ir,
)


def question_html(doc: dict, practice_id: str, prefix: str) -> str:
    """单题文档 → 题目体 HTML（题号/分值并入首个段落，与整册/旧块渲染一致）。"""
    return question_html_from_ir(doc, practice_id, prefix)
