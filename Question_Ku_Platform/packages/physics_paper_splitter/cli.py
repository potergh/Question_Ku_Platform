from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

from .pipeline import SplitPipeline, discover_pdfs


def build_output_names(pdfs: list[Path]) -> dict[Path, str]:
    """为批次内重名 PDF 生成稳定且互不覆盖的输出目录名。"""
    stem_counts = Counter(path.stem.casefold() for path in pdfs)
    names: dict[Path, str] = {}
    for path in pdfs:
        name = path.stem
        if stem_counts[path.stem.casefold()] > 1:
            source_key = str(path.resolve()).casefold().encode("utf-8")
            digest = hashlib.sha256(source_key).hexdigest()[:8]
            name = f"{path.stem}_{digest}"
        names[path] = name
    return names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地物理试卷 PDF 逐题高清切分")
    parser.add_argument("input", type=Path, help="一个 PDF 文件或包含 PDF 的目录")
    parser.add_argument("--output", type=Path, default=Path("output"), help="输出根目录")
    parser.add_argument("--dpi", type=int, default=300, help="渲染分辨率，默认 300 DPI")
    parser.add_argument("--quality", type=int, default=92, help="WebP 质量，默认 92")
    parser.add_argument(
        "--ocr-engine",
        choices=("auto", "none", "rapidocr"),
        default="auto",
        help="普通文字 OCR 引擎；auto 在已安装时启用 RapidOCR",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    pdfs = discover_pdfs(input_path)
    if not pdfs:
        print(f"未找到 PDF：{input_path}", file=sys.stderr)
        return 2

    pipeline = SplitPipeline(dpi=args.dpi, webp_quality=args.quality, ocr_engine=args.ocr_engine)
    output_names = build_output_names(pdfs)
    failed = 0
    for pdf_path in pdfs:
        try:
            manifest = pipeline.process(pdf_path, output_path, document_name=output_names[pdf_path])
            print(
                f"[完成] {pdf_path.name}: {manifest['question_count']} 题，"
                f"跨页题 {manifest['cross_page_questions']}"
            )
            for warning in manifest["warnings"]:
                print(f"  [警告] {warning}")
        except Exception as exc:  # 单份失败不阻断整个批次
            failed += 1
            print(f"[失败] {pdf_path}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
