"""把某份 golden 产物的答案抽成人工核对清单（HTML），供对着 PDF 答案区逐题比对。

用法：
    ../venv/Scripts/python.exe scripts/_make_answer_checklist.py <extract.json> <输出.html>
    # 可选：套用「确定性解析修复」重算答案（不调用模型）
    ../venv/Scripts/python.exe scripts/_make_answer_checklist.py <extract.json> <输出.html> \
        --pdf <原卷.pdf> --question-page-count 11

带 --pdf 时，answer_key_regex 那一路的答案会用当前代码重新解析一遍再参与选择。
和平卷的三处缺陷（第 20 题答案被写成【分析】首行、第 21 题只取到第一小问）都
出在这一路，因此不重跑整条管线也能拿到修正后的答案，用于人工核对。
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "packages"))

# 题目正文提到「图」但没抓到图的，是内容缺失，人工核对时必须一并看
FIGURE_WORDS = ("如图", "下图", "图中", "图所示", "图象", "图线", "如图甲", "如图乙")
# 答案本身就是一张图的典型写法：这些文字不是答案，是「答案在图里」的指路牌。
FIGURE_ANSWER_WORDS = ("如上图", "如图", "见图", "图略", "图甲", "图乙", "图丙", "上图2")


def figure_missing(item: dict) -> bool:
    """题干提到图却没抓到图。

    只看 stem_md：raw_text 是从裁剪区间取的原文字，实测会带上下一题的开头
    （第 21 题的 raw_text 末尾粘着「22．如图所示电路中…」），拿它判会误报。
    """
    text = item.get("stem_md") or item.get("raw_text") or ""
    return any(word in text for word in FIGURE_WORDS) and not (item.get("figures") or [])


def answer_is_figure(answer: str) -> bool:
    """答案正文只是「如上图所示」这类指路牌，真正的答案在插图里。"""
    text = (answer or "").strip()
    if not text:
        return False
    return any(word in text for word in FIGURE_ANSWER_WORDS)


def answer_missing_but_figure(item: dict) -> bool:
    """答案字段为空，却在答案区找到了该题解析且解析里提到图 —— 原卷答案就是图。

    第 20 题即如此：卷面「【答案】」下面是那幅标了 R₁=15Ω、R₂=10Ω 的电路图，
    没有任何文字，因此 answer 只能是空的，必须翻 PDF 看图。
    """
    if (item.get("answer") or "").strip():
        return False
    if not (item.get("answer_sources") or []):
        return False
    text = item.get("explanation") or ""
    return any(word in text for word in FIGURE_WORDS + ("图甲", "图乙", "图丙"))


def answer_looks_inferred(item: dict) -> bool:
    """模型在原文只有图的情况下把答案「描述」了出来，需要人判。"""
    answer = (item.get("answer") or "").strip()
    if item.get("answer_origin") != "answer_key_llm" or not answer:
        return False
    return "未提供图像" in answer or "仅文字描述" in answer or "见解析" in answer


def apply_recompute(data: dict, pdf: Path, question_page_count: int) -> int:
    """用当前代码重算 answer_key_regex 那一路，返回被改动的题数。"""
    import pymupdf as fitz

    from app.services.api_extract.answers import ORIGIN_PRIORITY, _normalize_answer
    from physics_paper_splitter.answers import parse_answers
    from physics_paper_splitter.models import DocumentInspection

    doc = fitz.open(pdf)
    inspection = DocumentInspection(
        pdf_path=pdf,
        page_count=len(doc),
        question_page_count=question_page_count,
        answer_start_page=question_page_count + 1,
        pages=[],
    )
    regex_by_number = parse_answers(doc, inspection)["questions"]

    changed = 0
    for item in data.get("items", []):
        number = item.get("question_number")
        sources = item.get("answer_sources") or []
        rebuilt: list[dict] = []
        touched = False
        for source in sources:
            if source.get("origin") == "answer_key_regex":
                parsed = regex_by_number.get(number) or {}
                if parsed.get("answer") or parsed.get("analysis"):
                    rebuilt.append(
                        {
                            "origin": "answer_key_regex",
                            "label": str(number),
                            "answer": parsed.get("answer"),
                            "explanation": parsed.get("analysis"),
                        }
                    )
                    touched = True
                continue
            rebuilt.append(source)
        if not touched:
            continue

        ordered = sorted(rebuilt, key=lambda e: ORIGIN_PRIORITY.get(e.get("origin"), 99))
        new_answer = next((e.get("answer") for e in ordered if e.get("answer")), None)
        distinct = {_normalize_answer(e.get("answer")) for e in ordered if e.get("answer")}
        if (item.get("answer") or "") != (new_answer or ""):
            changed += 1
        item["answer"] = new_answer
        item["answer_sources"] = rebuilt
        item["answer_conflict"] = len(distinct) > 1
    return changed


def _data_url(path: Path) -> str:
    import base64

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def load_answer_figures(data: dict, document_dir: Path) -> dict[int, list[str]]:
    """读产物里已抽好的答案图（权威结果），返回 题号 -> [data URL]。

    只有旧产物（还没有 answer_figures 字段的）才需要走下面按 PDF 离线重抽的
    兜底路径 —— 清单显示的内容要和产物一致，不能各算各的。
    """
    thumbnails: dict[int, list[str]] = {}
    for item in data.get("items", []):
        paths = item.get("answer_figures") or []
        urls = [
            _data_url(document_dir / relative)
            for relative in paths
            if (document_dir / relative).exists()
        ]
        if urls:
            thumbnails[item.get("question_number")] = urls
    return thumbnails


def build_answer_figure_thumbnails(
    data: dict, pdf: Path, question_page_count: int, tmp_dir: Path
) -> dict[int, list[str]]:
    """离线裁出答案区插图并内联成 data URL，返回 题号 -> [data URL]。

    走的是 service 里同一条 plan/extract 逻辑，但不调任何模型；内联是为了让
    清单单独一个文件就能看图 —— 相对路径的图片在静态预览里会 404。
    """
    import base64

    import pymupdf as fitz

    from app.services.api_extract.answer_figures import (
        answer_needs_figures,
        extract_answer_figures,
        plan_answer_figures,
    )
    from app.services.api_extract.answers import trailing_number
    from physics_paper_splitter.lines import extract_line_inventory

    doc = fitz.open(pdf)
    lines = extract_line_inventory(doc, range(question_page_count, doc.page_count))
    wanted: set[int] = set()
    for item in data.get("items", []):
        number = trailing_number(item.get("label"))
        if number is None:
            continue
        if answer_needs_figures(item.get("answer"), bool(item.get("answer_sources"))):
            wanted.add(number)

    plans = plan_answer_figures(doc, lines, wanted)
    paths_by_number = extract_answer_figures(doc, plans, tmp_dir)

    thumbnails: dict[int, list[str]] = {}
    for number, paths in paths_by_number.items():
        urls: list[str] = []
        for relative in paths:
            file = tmp_dir / Path(relative).name
            if not file.exists():
                continue
            encoded = base64.b64encode(file.read_bytes()).decode("ascii")
            urls.append(f"data:image/webp;base64,{encoded}")
        if urls:
            thumbnails[number] = urls
    return thumbnails


def build(source: Path, target: Path, pdf: Path | None, question_page_count: int) -> None:
    data = json.loads(source.read_text(encoding="utf-8"))
    recomputed = 0
    figure_thumbs = load_answer_figures(data, source.parent)
    if pdf is not None:
        recomputed = apply_recompute(data, pdf, question_page_count)
        # 产物还没带答案图（旧产物）时才从 PDF 重抽一份。
        if not figure_thumbs:
            with tempfile.TemporaryDirectory() as tmp:
                figure_thumbs = build_answer_figure_thumbnails(
                    data, pdf, question_page_count, Path(tmp)
                )

    conflicts = set(data.get("answer_report", {}).get("conflicts") or [])
    items = data.get("items", [])
    doc_name = data.get("source_name") or source.parent.name.replace("__golden", "")

    cards: list[str] = []
    for item in items:
        number = item.get("question_number")
        answer = (item.get("answer") or "").strip()
        warns = [w for w in (item.get("warnings") or []) if "不一致" not in w]
        tags: list[str] = []
        if number in conflicts:
            tags.append('<span class="tag t-red">答案来源冲突 · 必看</span>')
        if answer_is_figure(answer):
            tags.append('<span class="tag t-red">答案是图 · 必须对照 PDF 看图</span>')
        if answer_missing_but_figure(item):
            tags.append('<span class="tag t-red">答案为空 · 卷面答案是图</span>')
        if answer_looks_inferred(item):
            tags.append('<span class="tag t-red">模型推断的答案 · 原文只有图</span>')
        if not answer and not answer_is_figure(answer) and not answer_missing_but_figure(item):
            tags.append('<span class="tag t-red">答案为空</span>')
        if figure_missing(item):
            tags.append('<span class="tag t-amber">正文提到图但没抓到图</span>')
        elif not (item.get("figures") or []):
            tags.append('<span class="tag t-amber">无插图</span>')
        origin = item.get("answer_origin") or "无"
        origin_text = {
            "answer_key_llm": "AI 抄的（文末答案区）",
            "answer_key_regex": "规则抄的（按题号顺序，易错）",
            "inline": "题干里自带的",
        }.get(origin, origin)

        thumbs = figure_thumbs.get(number) or []
        figure_html = ""
        if thumbs:
            figure_html = (
                '<div class="ans-figs"><span class="fig-cap">答案区插图（'
                + str(len(thumbs))
                + ' 张）</span>'
                + "".join(f'<img src="{url}" alt="第 {number} 题答案图" />' for url in thumbs)
                + "</div>"
            )

        warn_html = ""
        if warns:
            warn_html = (
                '<details class="warns"><summary>AI 的提醒（'
                + str(len(warns))
                + " 条）</summary><ul>"
                + "".join(f"<li>{html.escape(w[:200])}</li>" for w in warns)
                + "</ul></details>"
            )

        cards.append(
            f"""
<section class="card{' hot' if number in conflicts else ''}">
  <div class="head">
    <span class="no">第 {number} 题</span>
    <span class="meta">卷面第 {item.get('start_page')}–{item.get('end_page')} 页</span>
    <span class="meta">插图 {len(item.get('figures') or [])} 张</span>
    <label class="tick"><input type="checkbox"> 与 PDF 原文一致</label>
  </div>
  <div class="tags">{''.join(tags)}</div>
  <div class="src">答案来源：{html.escape(origin_text)}</div>
  <div class="answer">{html.escape(answer) if answer else '<i>（空）</i>'}</div>
  {figure_html}
  {warn_html}
</section>"""
        )

    conflict_list = "、".join(f"第 {n} 题" for n in sorted(conflicts))
    body = "".join(cards)
    figure_total = sum(len(urls) for urls in figure_thumbs.values())
    recompute_note = (
        f'<p class="lede">已用当前代码重算确定性解析：{recomputed} 题的答案发生变化；'
        f'并从文末答案区裁出 {figure_total} 张答案插图（{len(figure_thumbs)} 道题）。</p>'
        if pdf is not None
        else ""
    )
    target.write_text(
        f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>答案人工核对清单 · {html.escape(doc_name)}</title>
<style>
  :root {{ --line:#d8dce3; --ink:#1c1f24; --sub:#5b6472; --bg:#f6f7f9;
          --red:#b3261e; --amber:#8a5a00; --green:#1f6f43; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:28px 32px 64px; background:var(--bg); color:var(--ink);
         font:15px/1.65 "Noto Sans SC","Microsoft YaHei","PingFang SC",system-ui,sans-serif; }}
  h1 {{ font-size:21px; margin:0 0 6px; }}
  .lede {{ color:var(--sub); margin:0 0 4px; }}
  .how {{ background:#fff; border:1px solid var(--line); border-left:3px solid var(--ink);
          padding:14px 18px; border-radius:3px; margin:18px 0 26px; }}
  .how ol {{ margin:6px 0 0; padding-left:22px; }}
  .how li {{ margin:3px 0; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:3px;
           padding:14px 18px 16px; margin:0 0 12px; }}
  .card.hot {{ border-left:4px solid var(--red); }}
  .head {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }}
  .no {{ font-weight:700; font-size:16px; }}
  .meta {{ color:var(--sub); font-size:13px; }}
  .tick {{ margin-left:auto; font-size:13px; color:var(--sub); user-select:none; }}
  .tags {{ margin:8px 0 0; display:flex; gap:6px; flex-wrap:wrap; }}
  .tag {{ font-size:12px; padding:1px 7px; border-radius:10px; border:1px solid var(--line); }}
  .t-red {{ color:var(--red); border-color:#e8b4b0; background:#fdf2f1; }}
  .t-amber {{ color:var(--amber); border-color:#e6d3a8; background:#fdf8ee; }}
  .src {{ color:var(--sub); font-size:13px; margin-top:8px; }}
  .answer {{ margin-top:6px; padding:10px 12px; background:#fafbfc;
             border:1px solid var(--line); border-radius:3px; white-space:pre-wrap;
             font-size:14px; }}
  .ans-figs {{ margin-top:8px; padding:8px 10px; background:#fffdf7;
               border:1px solid #e6d3a8; border-radius:3px; }}
  .fig-cap {{ display:block; font-size:12px; color:var(--amber); margin-bottom:6px; }}
  .ans-figs img {{ max-width:260px; max-height:260px; margin:0 6px 6px 0;
                   border:1px solid var(--line); background:#fff; vertical-align:top; }}
  .warns {{ margin-top:8px; font-size:13px; color:var(--sub); }}
  .warns ul {{ margin:6px 0 0; padding-left:20px; }}
  @media print {{ body {{ background:#fff; padding:0; }} .card {{ break-inside:avoid; }} }}
</style></head>
<body>
<h1>答案人工核对清单</h1>
<p class="lede">{html.escape(doc_name)} · 共 {len(items)} 题 · 答案来源冲突的题需重点看：{conflict_list or "无"}</p>
{recompute_note}

<div class="how">
  <b>怎么核对</b>
  <ol>
    <li>打开原卷 PDF，翻到<b>答案区起始页</b>（这份卷子是第 12 页，页首写着「参考答案与试题解析」）。</li>
    <li>按题号找到该题的答案解析，与下面卡片里的答案<b>逐字比对</b>——数字、单位、小问序号都要看。</li>
    <li>一致就勾选；不一致或拿不准，在纸上记下题号，先别入库。</li>
    <li>红标「答案来源冲突」的题：机器从两个来源抄到了不同内容，选了其中一个，<b>必须人判</b>。</li>
    <li>红标<b>「答案是图」</b>的题：卷面答案就是一幅插图（如第 20 题的电路图、第 24 题的描点图象），
        文字里只会写「如上图所示」。这类题下方已直接列出从答案区裁出的插图，
        <b>对着 PDF 原页确认这些图是否裁全、是否就是本题的答案</b>。</li>
    <li>橙标「正文提到图但没抓到图」的题：就算答案对，题干也缺图，这类题不能直接用。</li>
  </ol>
  <p style="margin:8px 0 0;color:var(--sub);font-size:13px">
    勾选状态不会保存，刷新即重置——这是纯核对清单，不是录入工具。</p>
</div>
{body}
</body></html>""",
        encoding="utf-8",
    )
    print(f"写出 {target}（{len(items)} 题，冲突 {len(conflicts)} 题，重算改动 {recomputed} 题）")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--question-page-count", type=int, default=0)
    args = parser.parse_args()
    build(
        Path(args.source),
        Path(args.target),
        Path(args.pdf) if args.pdf else None,
        args.question_page_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
