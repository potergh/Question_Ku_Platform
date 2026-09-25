"""生成 OCR golden regression 语料 —— 对应 `tests/test_ocr_regression.py`。

用法（工作目录 backend/）：
    python scripts/make_golden_corpus.py                # 处理 test_data/ 下全部 PDF
    python scripts/make_golden_corpus.py "某卷.pdf"      # 只处理指定文件（名或路径）

产物（目录结构由 test_ocr_regression.get_golden_papers 决定，勿擅改）：
    test_data/expected/<pdf stem>/question_count.json    {"count": N}
    test_data/expected/<pdf stem>/question_numbers.json  [1, 2, 3, ...]
    test_data/expected/<pdf stem>/meta.json              {"pdf", "sha1", "generated_at"}

基线是"当前已人工认可的切题结果"，不是"正确答案"。OCR 改动后重跑测试，
数量下降即视为回归；确需接受新行为时，用本脚本重新生成基线并在提交信息里说明原因。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.services.ocr_adapter import OCRAdapter  # noqa: E402

TEST_DATA_DIR = PROJECT_ROOT / "test_data"
EXPECTED_ROOT = TEST_DATA_DIR / "expected"


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def generate(adapter: OCRAdapter, pdf_path: Path) -> dict:
    # 复用线上同一输出根目录：pipeline 需要真实可写的 Path
    result = adapter.process_pdf(pdf_path, settings.ocr_output_dir)
    if result.question_count == 0:
        # 0 题基线是"空转"：count>=0*0.9 恒真，会把回归测试变成假绿灯。
        # 扫描件无文字层时最常见，必须显式拒绝而不是落一份空基线。
        warnings = "；".join(result.warnings) or "无警告信息"
        raise RuntimeError(f"切出 0 题，不生成基线（{warnings}）")
    numbers = sorted(q.question_number for q in result.questions)
    out_dir = EXPECTED_ROOT / pdf_path.stem
    _write(out_dir / "question_count.json", {"count": result.question_count})
    _write(out_dir / "question_numbers.json", numbers)
    _write(out_dir / "meta.json", {
        "pdf": pdf_path.name,
        "sha1": _sha1(pdf_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    })
    return {"pdf": pdf_path.name, "count": result.question_count, "numbers": len(numbers)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 OCR golden corpus 基线")
    parser.add_argument("pdf", nargs="?", help="只处理该 PDF（文件名或路径），缺省=全部")
    args = parser.parse_args(argv)

    if not TEST_DATA_DIR.exists():
        print(f"[ERROR] 找不到 {TEST_DATA_DIR}", file=sys.stderr)
        return 1

    if args.pdf:
        candidate = Path(args.pdf)
        pdfs = [candidate if candidate.exists() else TEST_DATA_DIR / args.pdf]
    else:
        pdfs = sorted(TEST_DATA_DIR.glob("*.pdf"))

    if not pdfs:
        print(f"[ERROR] {TEST_DATA_DIR} 下没有 PDF", file=sys.stderr)
        return 1

    adapter = OCRAdapter()
    failed: list[str] = []
    for pdf_path in pdfs:
        if not pdf_path.exists():
            print(f"[SKIP] 不存在：{pdf_path}", file=sys.stderr)
            failed.append(pdf_path.name)
            continue
        print(f"[RUN ] {pdf_path.name} ...", flush=True)
        try:
            info = generate(adapter, pdf_path)
        except Exception as exc:  # noqa: BLE001 — 单份失败不阻断其余样本
            print(f"[FAIL] {pdf_path.name}：{exc}", file=sys.stderr, flush=True)
            failed.append(pdf_path.name)
            continue
        print(f"[DONE] {info['pdf']}：{info['count']} 题 → "
              f"{EXPECTED_ROOT / pdf_path.stem}", flush=True)

    if failed:
        print(f"[WARN] {len(failed)} 份未能生成基线：{', '.join(failed)}", file=sys.stderr)
        print("[HINT] 无文字层的扫描件需要 `rapidocr_onnxruntime`（见设计文档 §10.4）；"
              "或改用 api_extract 通道生成。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
