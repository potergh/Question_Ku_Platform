"""篇章题「小题答案」拆分回填（英语通道专用）。

背景（2023 河西英语实测）：完形/阅读/听力长对话被正确拆成一个个带 (1)(2)… 编号的
小题后，答案区里仍常是**整组一条**的形态——例如 `32．（1）` 的 answer 塞着
「（1）B\n（2）C\n…（10）C」，而 `32．（2）…（10）` 的 answer 全空。整份 68 题里
28 题因此被标 `no_answer`。

这里做**确定性**回填：把带 (k) 序号的答案串按小题序号拆开，各归各的小题。不调模型、
不猜内容——只搬运本来就写在一起的字母/短句。仅供英语通道调用，物理/数学/化学不走这里。
"""

from __future__ import annotations

import re

# label 形如「32．（1）」「15.（2）」「44．」：前导主编号 + 可选的括号小问序号。
_PARENT_RE = re.compile(r"^\D*?(\d+)")
_SUB_RE = re.compile(r"[（(]\s*(\d{1,2})\s*[)）]\s*$")
# 答案串里的小问条目：「（1）B」「（10）C」「（2）only the first sentence」。
_ENTRY_RE = re.compile(r"[（(]\s*(\d{1,2})\s*[)）]\s*([^\n（(]*)")
# 纯字母答案（听力/选择），用于「ACDCB」这类无序号串的按位拆分兜底。
_LETTERS_RE = re.compile(r"^[A-Ha-h]+$")


def _parent_and_sub(label: str) -> tuple[int | None, int | None]:
    parent = _PARENT_RE.search(label or "")
    sub = _SUB_RE.search((label or "").strip())
    return (
        int(parent.group(1)) if parent else None,
        int(sub.group(1)) if sub else None,
    )


def _split_blob(blob: str) -> dict[int, str]:
    """把整组答案串拆成 {小题序号: 答案}。认不出来就返回空。"""
    entries = {int(k): v.strip() for k, v in _ENTRY_RE.findall(blob) if v.strip()}
    if len(entries) >= 2:
        return entries
    return {}


def _positional_letters(blob: str, subs: list[int]) -> dict[int, str]:
    """无序号但答案是一串纯字母（如「ACDCB」）时，按小题顺序逐位分配。"""
    clean = re.sub(r"[\s、,，.。]+", "", blob or "")
    if len(subs) >= 2 and _LETTERS_RE.match(clean) and len(clean) == len(subs):
        return {sub: clean[i] for i, sub in enumerate(sorted(subs))}
    return {}


def distribute_group_answers(items: list) -> int:
    """把篇章题「挤在一条里」的整组答案拆分回填到各小题，返回新填上的小题数。

    只处理同一主编号下、label 带 (k) 序号且成员数 >= 2 的分组；对没有整组答案
    串的组（如某些阅读篇没匹配到答案）保持原样，交给复核页人工处理。
    """
    groups: dict[int, list] = {}
    for item in items:
        if getattr(item, "excluded", False):
            continue
        parent, sub = _parent_and_sub(getattr(item, "label", "") or "")
        if parent is None or sub is None:
            continue
        groups.setdefault(parent, []).append(item)

    filled = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        subs = [_parent_and_sub(m.label)[1] for m in members]
        subs = [s for s in subs if s is not None]
        # 找整组答案串：优先带 (k) 序号的 blob；否则退到纯字母按位分配。
        blob = ""
        for m in members:
            ans = (m.answer or "").strip()
            if ans and len(_split_blob(ans)) >= 2:
                blob = ans
                break
        if blob:
            mapping = _split_blob(blob)
        else:
            for m in members:
                ans = (m.answer or "").strip()
                cand = _positional_letters(ans, subs)
                if cand:
                    blob, mapping = ans, cand
                    break
            else:
                mapping = {}
        if not mapping:
            continue

        for m in members:
            sub = _parent_and_sub(m.label)[1]
            value = mapping.get(sub)
            if not value:
                continue
            if (m.answer or "").strip() == value:
                continue
            was_empty = not (m.answer or "").strip()
            m.answer = value
            if was_empty:
                filled += 1
                flags = getattr(m, "audit_flags", None)
                if flags and "no_answer" in flags:
                    m.audit_flags = [f for f in flags if f != "no_answer"]
    return filled


def _sub_index(label: str) -> int | None:
    """从小题 label（如「（3）」「3.)」）里取小问序号；取不到返回 None。"""
    match = re.search(r"[（(]\s*(\d{1,2})\s*[)）]", label or "")
    if match:
        return int(match.group(1))
    lead = re.match(r"^\s*(\d{1,2})", label or "")
    return int(lead.group(1)) if lead else None


def distribute_answers_into_subquestions(items: list) -> int:
    """把篇章题（整篇一条）携带的**整组答案串**按 (k) 序号拆开，写进各小题。

    适用于两级模型：一道篇章题 item 的 stem_md 是材料、sub_questions 是各小题，
    而答案区归并到本题的 answer 常是「（1）B\n（2）C…」整组串。本函数只搬运本就写
    在一起的字母/短句，不调模型、不猜内容。返回新填上答案的小题数。
    """
    filled = 0
    for item in items:
        if getattr(item, "excluded", False):
            continue
        subs = getattr(item, "sub_questions", None) or []
        if len(subs) < 2:
            continue
        # 小题已有答案的不参与（模型内联给全了）。
        need = [s for s in subs if not str(s.get("answer") or "").strip()]
        if not need:
            continue
        blob = (getattr(item, "answer", "") or "").strip()
        if not blob:
            continue
        indices = [_sub_index(str(s.get("label") or "")) for s in subs]
        mapping = _split_blob(blob)
        if not mapping:
            mapping = _positional_letters(
                blob, [i for i in indices if i is not None]
            )
        if not mapping:
            continue
        for sub, idx in zip(subs, indices):
            if idx is None or str(sub.get("answer") or "").strip():
                continue
            value = mapping.get(idx)
            if value:
                sub["answer"] = value
                filled += 1
        # 顶层 answer 保留（整组串）：篇章题的「答案见下」就是这整组，
        # 而且答案覆盖率审计按顶层 answer 是否存计——清掉会把已答好的语篇题误计为缺答。
    return filled
