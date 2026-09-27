"""识别管线耗时分析器（离线·只读·零成本，不进 pytest）。

回答一个问题：**「一份卷识别为什么要几分钟到十几分钟，时间花在哪、哪份卷异常」**。

数据来源是已经导入/识别过的暂存文件 ``<ocr_output>/**/extract.json``，
里面已经带了每次识别的：
  - ``timings``：5 段墙钟打点（行清单 / 边界判定 / 裁卡与抽图 / 逐题结构化 / 答案归一 + 审计）
  - ``usage``：全程大模型用量（calls / prompt_tokens / completion_tokens / by_model）
  - ``question_count`` / ``document_name`` / ``channel``

本脚本只做「读 + 聚合 + 归因 + 出报告」，不改任何生产逻辑、不重跑识别、不花 token。

用法（在 ``backend/`` 目录下）::

    python -m scripts.analyze_extract_timings                 # 默认扫描 settings.ocr_output_dir
    python -m scripts.analyze_extract_timings --root D:\\path\\to\\ocr_output
    python -m scripts.analyze_extract_timings --no-file       # 只打印，不落盘
    python -m scripts.analyze_extract_timings --md out.md --json out.json

落盘默认写到 ``backend/reports/timing_report.{md,json}``。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# timings 里固定按这个顺序展示（审计通常 ~0，放最后）。
STAGE_ORDER = ["行清单", "边界判定", "裁卡与抽图", "逐题结构化", "答案归一", "审计"]
# 科目推断：从文档名里的关键词判断，命中即取（顺序无关，关键词互斥）。
SUBJECT_KEYWORDS = {
    "英语": "英语",
    "数学": "数学",
    "物理": "物理",
    "化学": "化学",
    "生物": "生物",
    "语文": "语文",
}


def _default_root() -> Path:
    """默认扫描目录 = settings.ocr_output_dir；导入失败则退回相对路径。"""
    try:
        from app.config import settings  # noqa: WPS433 — 延迟导入，脚本可脱离依赖运行

        return Path(settings.ocr_output_dir)
    except Exception:  # noqa: BLE001 — 任何导入/属性问题都不该让分析脚本崩
        return BACKEND_DIR / "data" / "ocr_output"


def infer_subject(text: str) -> str:
    for keyword, subject in SUBJECT_KEYWORDS.items():
        if keyword in text:
            return subject
    return "其他"


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def load_docs(root: Path) -> tuple[list[dict], list[str]]:
    """扫描 root 下所有 extract.json，抽出分析需要的字段。返回 (文档列表, 跳过说明)。"""
    docs: list[dict] = []
    skipped: list[str] = []
    for path in sorted(root.rglob("extract.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append(f"{path.parent.name}：读取失败（{exc}）")
            continue
        timings = raw.get("timings") or {}
        if not timings:
            skipped.append(f"{path.parent.name}：无 timings（老暂存文件，跳过）")
            continue
        usage = raw.get("usage") or {}
        items = raw.get("question_count") or 0
        # 只保留 timings 里真实出现且 > 0 的阶段，审计常年为 0 也一并留着但不计入占比。
        stages = {k: float(v) for k, v in timings.items() if isinstance(v, (int, float))}
        total = round(sum(stages.values()), 1)
        calls = int(usage.get("calls") or 0)
        tokens = int(usage.get("total_tokens") or 0)
        name = raw.get("document_name") or path.parent.name
        docs.append(
            {
                "dir": path.parent.name,
                "name": name,
                "subject": infer_subject(f"{name}{path.parent.name}"),
                "channel": raw.get("channel") or "",
                "items": items,
                "total_s": total,
                "stages": stages,
                "calls": calls,
                "tokens": tokens,
                "per_item_s": _round(total / items, 2) if items else None,
                "tokens_per_call": _round(tokens / calls, 0) if calls else None,
                "calls_per_item": _round(calls / items, 2) if items else None,
            }
        )
    return docs, skipped


def stage_shares(doc: dict) -> dict[str, float]:
    total = doc["total_s"] or 0
    if not total:
        return {}
    return {k: round(v / total * 100, 1) for k, v in doc["stages"].items()}


def aggregate_stages(docs: list[dict]) -> list[dict]:
    """按阶段汇总：平均/中位/最大耗时、平均占比、'几份卷里它是头号瓶颈'。"""
    rows: list[dict] = []
    for stage in STAGE_ORDER + [
        s for d in docs for s in d["stages"] if s not in STAGE_ORDER
    ]:
        if any(stage not in d["stages"] for d in docs):
            pass  # 允许部分文档缺某阶段，只统计有的
        seconds = [d["stages"][stage] for d in docs if stage in d["stages"]]
        if not seconds:
            continue
        shares = [stage_shares(d).get(stage, 0.0) for d in docs if stage in d["stages"]]
        rows.append(
            {
                "stage": stage,
                "count": len(seconds),
                "mean_s": _round(statistics.mean(seconds)),
                "median_s": _round(statistics.median(seconds)),
                "max_s": _round(max(seconds)),
                "min_s": _round(min(seconds)),
                "mean_share_pct": _round(statistics.mean(shares)),
                "top_in_n_docs": sum(
                    1
                    for d in docs
                    if d["stages"] and max(d["stages"], key=d["stages"].get) == stage
                ),
            }
        )
    # 去掉全 0 的审计行占比噪声，但仍保留展示
    rows.sort(key=lambda r: (r["mean_share_pct"] or 0), reverse=True)
    return rows


def build_findings(docs: list[dict], stage_rows: list[dict]) -> list[str]:
    """把数字翻译成结论性要点（瓶颈 / 系统性开销 / 方差 / 异常卷）。"""
    findings: list[str] = []
    if not docs:
        return ["没有可分析的 extract.json。"]

    totals = [d["total_s"] for d in docs]
    mean_total = statistics.mean(totals)

    # 1) 头号瓶颈阶段
    if stage_rows:
        top = stage_rows[0]
        findings.append(
            f"整体头号瓶颈是「{top['stage']}」：平均占比 {top['mean_share_pct']}%"
            f"（平均 {top['mean_s']}s，最慢一份 {top['max_s']}s），"
            f"在 {top['top_in_n_docs']}/{len(docs)} 份卷里都是单卷最大耗时段。"
        )

    # 2) 系统性开销：某阶段在「多数」卷里都排前二
    for row in stage_rows:
        if row["mean_share_pct"] and row["mean_share_pct"] >= 25 and row["count"] >= max(
            2, len(docs) // 2
        ):
            findings.append(
                f"「{row['stage']}」是**系统性开销**：跨科目平均占比 "
                f"{row['mean_share_pct']}%（覆盖 {row['count']} 份卷），"
                f"不是个别卷子的问题，优先归因这里收益最大。"
            )

    # 3) 方差最大的阶段（时快时慢 → 强依赖输入）
    driver_hint = {
        "行清单": "扫描/公式页是否触发视觉模型整页转写（有文字层的卷子近乎 0，扫描件要逐页转写）",
        "逐题结构化": "题量 × 单题 prompt 规模（两级语篇题更大）× 并发是否吃满",
        "边界判定": "行数与分批并发；整篇成组的语篇题会推高单次输入",
        "答案归一": "答案区规模与是否走 VLM 解析（文末答案区大 / 三源对照更慢）",
        "裁卡与抽图": "页数与图片数量（本地抽图 vs MinerU 版面切图）",
    }
    variable = [
        r
        for r in stage_rows
        if r["count"] >= 2 and (r["max_s"] or 0) - (r["min_s"] or 0) > 20
    ]
    if variable:
        v = max(variable, key=lambda r: (r["max_s"] or 0) - (r["min_s"] or 0))
        hint = driver_hint.get(v["stage"], "输入规模差异")
        findings.append(
            f"「{v['stage']}」耗时方差最大（{v['min_s']}s ~ {v['max_s']}s）："
            f"该段强依赖输入，根因方向是{hint}。"
        )
    # 行清单的相对剧变单独点一句（绝对差未必最大，但 0~几十秒的比值最扎眼）
    inv = next((r for r in stage_rows if r["stage"] == "行清单" and r["count"] >= 2), None)
    if inv and (inv["min_s"] or 0) <= 1 and (inv["max_s"] or 0) >= 20:
        findings.append(
            f"「行清单」在 {inv['min_s']}s ~ {inv['max_s']}s 之间剧变："
            f"取决于该卷是否有扫描/公式页需要视觉模型整页转写——"
            f"纯文字层卷子几乎不耗时。"
        )

    # 4) 异常卷（总耗时显著高于均值）
    if len(docs) >= 3:
        std = statistics.pstdev(totals) or 0.0
        outliers = [d for d in docs if d["total_s"] > mean_total + std]
        for d in sorted(outliers, key=lambda x: x["total_s"], reverse=True):
            shares = stage_shares(d)
            top_stage = max(shares, key=shares.get) if shares else "-"
            findings.append(
                f"异常卷：「{d['name']}」总耗时 {d['total_s']}s，"
                f"显著高于均值 {round(mean_total, 1)}s（{len(docs)} 份均值）；"
                f"主要来自「{top_stage}」占 {shares.get(top_stage, 0)}%。"
            )

    # 5) 单题均摊最高（题多 + prompt 大 → 结构化被推高）
    priced = [d for d in docs if d["per_item_s"]]
    if priced:
        worst = max(priced, key=lambda d: d["per_item_s"])
        best = min(priced, key=lambda d: d["per_item_s"])
        findings.append(
            f"单题均摊：最贵「{worst['name']}」{worst['per_item_s']}s/题"
            f"（{worst['items']} 题），最省「{best['name']}」{best['per_item_s']}s/题；"
            f"差距主要来自题型结构（如英语两级语篇题的 prompt 更大）与并发是否吃满。"
        )

    return findings


def build_report(root: Path, docs: list[dict], skipped: list[str]) -> dict:
    totals = [d["total_s"] for d in docs]
    return {
        "root": str(root),
        "doc_count": len(docs),
        "skipped": skipped,
        "summary": {
            "total_s_mean": _round(statistics.mean(totals)) if totals else None,
            "total_s_min": _round(min(totals)) if totals else None,
            "total_s_max": _round(max(totals)) if totals else None,
        },
        "docs": [
            {
                **{k: d[k] for k in (
                    "name", "subject", "channel", "items", "total_s",
                    "per_item_s", "calls", "tokens", "tokens_per_call", "calls_per_item",
                )},
                "stages": d["stages"],
                "shares_pct": stage_shares(d),
            }
            for d in sorted(docs, key=lambda x: x["total_s"], reverse=True)
        ],
        "stage_aggregate": aggregate_stages(docs),
        "findings": build_findings(docs, aggregate_stages(docs)),
    }


# ---------- 控制台/Markdown 渲染（CJK 宽度对齐） ----------

def _disp_width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in str(text))


def _pad(text: str, width: int) -> str:
    text = str(text)
    return text + " " * max(0, width - _disp_width(text))


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(_disp_width(h), *( _disp_width(c) for c in (r[i] for r in rows))) if rows else _disp_width(h) for i, h in enumerate(headers)]
    line = "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = [
        "  ".join(_pad(c, widths[i]) for i, c in enumerate(r)) for r in rows
    ]
    return "\n".join([line, sep, *body])


def render_console(report: dict) -> str:
    out: list[str] = []
    out.append(f"扫描目录：{report['root']}")
    out.append(
        f"可分析 {report['doc_count']} 份；"
        f"总耗时 均值 {report['summary']['total_s_mean']}s"
        f"（{report['summary']['total_s_min']}~{report['summary']['total_s_max']}s）"
    )
    if report["skipped"]:
        out.append(f"跳过 {len(report['skipped'])} 份：" + "；".join(report["skipped"]))
    out.append("")

    out.append("== 每份卷 ==")
    rows = []
    for d in report["docs"]:
        rows.append(
            [
                d["name"][:22],
                d["subject"],
                str(d["items"]),
                f"{d['total_s']}s",
                f"{d['per_item_s']}s" if d["per_item_s"] is not None else "-",
                f"{d['calls']}",
                f"{int(d['tokens'])}",
                f"{int(d['tokens_per_call'])}" if d["tokens_per_call"] else "-",
            ]
        )
    out.append(
        _table(
            ["卷子", "科目", "题数", "总耗时", "单题均摊", "调用", "tokens", "tok/调用"],
            rows,
        )
    )
    out.append("")

    out.append("== 阶段瓶颈排名（跨科目） ==")
    rows = []
    for r in report["stage_aggregate"]:
        rows.append(
            [
                r["stage"],
                f"{r['mean_share_pct']}%",
                f"{r['mean_s']}s",
                f"{r['median_s']}s",
                f"{r['min_s']}~{r['max_s']}s",
                f"{r['top_in_n_docs']}/{r['count']}",
            ]
        )
    out.append(
        _table(
            ["阶段", "平均占比", "平均", "中位", "区间", "头号瓶颈卷数"],
            rows,
        )
    )
    out.append("")

    out.append("== 结论 ==")
    for i, f in enumerate(report["findings"], 1):
        out.append(f"{i}. {f}")
    return "\n".join(out)


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    lines.append("# 识别管线耗时分析报告")
    lines.append("")
    lines.append(f"- 扫描目录：`{report['root']}`")
    s = report["summary"]
    lines.append(
        f"- 可分析 {report['doc_count']} 份；总耗时 均值 **{s['total_s_mean']}s**"
        f"（{s['total_s_min']}~{s['total_s_max']}s）"
    )
    if report["skipped"]:
        lines.append(f"- 跳过 {len(report['skipped'])} 份：{'; '.join(report['skipped'])}")
    lines.append("")

    lines.append("## 每份卷")
    lines.append("")
    lines.append("| 卷子 | 科目 | 题数 | 总耗时 | 单题均摊 | 调用数 | tokens | tok/调用 | 最慢阶段 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for d in report["docs"]:
        shares = d["shares_pct"]
        top_stage = max(shares, key=shares.get) if shares else "-"
        top_pct = shares.get(top_stage, 0) if shares else 0
        lines.append(
            f"| {d['name']} | {d['subject']} | {d['items']} | {d['total_s']}s | "
            f"{d['per_item_s']}s | {d['calls']} | {int(d['tokens'])} | "
            f"{int(d['tokens_per_call']) if d['tokens_per_call'] else '-'} | "
            f"{top_stage} {top_pct}% |"
        )
    lines.append("")

    lines.append("## 阶段瓶颈排名（跨科目）")
    lines.append("")
    lines.append("| 阶段 | 平均占比 | 平均 | 中位 | 区间 | 作为头号瓶颈的卷数 |")
    lines.append("|---|---|---|---|---|---|")
    for r in report["stage_aggregate"]:
        lines.append(
            f"| {r['stage']} | {r['mean_share_pct']}% | {r['mean_s']}s | {r['median_s']}s | "
            f"{r['min_s']}~{r['max_s']}s | {r['top_in_n_docs']}/{r['count']} |"
        )
    lines.append("")

    lines.append("## 结论")
    lines.append("")
    for f in report["findings"]:
        lines.append(f"- {f}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="识别管线耗时分析（离线·只读）")
    parser.add_argument("--root", default=None, help="ocr_output 根目录，默认 settings.ocr_output_dir")
    parser.add_argument("--md", default=None, help="Markdown 报告输出路径")
    parser.add_argument("--json", dest="json_out", default=None, help="JSON 报告输出路径")
    parser.add_argument("--no-file", action="store_true", help="只打印，不落盘")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else _default_root()
    if not root.is_dir():
        print(f"[错误] 目录不存在：{root}", file=sys.stderr)
        return 2

    docs, skipped = load_docs(root)
    report = build_report(root, docs, skipped)

    print(render_console(report))

    if args.no_file:
        return 0

    reports_dir = BACKEND_DIR / "reports"
    md_path = Path(args.md) if args.md else reports_dir / "timing_report.md"
    json_path = Path(args.json_out) if args.json_out else reports_dir / "timing_report.json"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[已写出] {md_path}")
    print(f"[已写出] {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
