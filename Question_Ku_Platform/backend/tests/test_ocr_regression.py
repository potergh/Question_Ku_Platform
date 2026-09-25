"""OCR Regression Test Framework.

Uses golden corpus to verify OCR accuracy hasn't degraded.

运行方式：
- 默认（快）：只跑廉价守卫（语料存在、无未登记缺口、适配层可导入），
  不真跑 OCR。
- 真跑 OCR 的回归（约 1.5–3 分钟/卷）：``pytest tests/test_ocr_regression.py -m slow``
- 两者一起：``pytest tests/test_ocr_regression.py -m "slow or not slow"``

为什么真跑 OCR 的用例默认跳过：装上 `rapidocr_onnxruntime`（设计文档 §10.4 要求）
之后，流水线对**每一道题**都会做 local OCR 融合，所以即使是有文字层的卷也要
约 85 秒 —— 不再是"只有扫描件才慢"。把这种开销塞进默认套件会拖垮日常开发循环，
故显式 opt-in；这也意味着**改 OCR 切分逻辑后必须记得跑 `-m slow`**。

Golden corpus structure（由 `scripts/make_golden_corpus.py` 生成，勿手改）::

    test_data/
    ├── 某卷.pdf
    └── expected/
        └── 某卷/                      # 目录名 = PDF 的 stem
            ├── question_count.json    → {"count": 12}
            ├── question_numbers.json  → [1, 2, 3, ..., 12]
            └── meta.json              → {"pdf", "sha1", "generated_at"}

基线含义：**当前已人工认可的切题结果**，不是"正确答案"。
数量下降即视为回归；确需接受新行为时重跑生成脚本，并在提交信息里写明原因。
"""

import json
import sys
from pathlib import Path

import pytest

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.ocr_adapter import OCRAdapter  # noqa: E402

TEST_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "test_data"
OCR_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "ocr_output"

# 已知无法离线生成基线的样本（stem → 原因）。当前为空：三份样本都已可拆。
# 新增 PDF 却忘了跑基线生成脚本时会由 test_no_undeclared_gap 报出来，
# 目的就是不让"缺基线"被静默忽略。
KNOWN_UNSUPPORTED: dict[str, str] = {}


def get_golden_papers():
    """Discover all papers with expected/ directories in test_data/."""
    papers = []
    if not TEST_DATA_DIR.exists():
        return papers
    for paper_dir in sorted(TEST_DATA_DIR.iterdir()):
        if paper_dir.suffix == ".pdf":
            expected_dir = paper_dir.parent / "expected" / paper_dir.stem
            if (expected_dir / "question_count.json").exists():
                papers.append((paper_dir, expected_dir))
    return papers


def _all_pdfs() -> list[Path]:
    return sorted(TEST_DATA_DIR.glob("*.pdf")) if TEST_DATA_DIR.exists() else []


def _paper_params():
    return [
        pytest.param(pdf, expected, id=pdf.stem)
        for pdf, expected in get_golden_papers()
    ]


_RESULTS: dict = {}


def _result_for(pdf: Path):
    """按需 OCR 并按卷缓存（两张用例共享一次真实跑批）。"""
    if pdf not in _RESULTS:
        _RESULTS[pdf] = OCRAdapter().process_pdf(pdf, OCR_OUTPUT_DIR)
    return _RESULTS[pdf]


class TestOCRRegression:
    """Regression tests for OCR accuracy."""

    def test_adapter_import(self):
        """Verify OCR adapter can be imported."""
        from app.services.ocr_adapter import OCRAdapter, QuestionData, OCRResult
        assert OCRAdapter is not None

    def test_golden_corpus_exists(self):
        """至少有 1 份可回归的 golden 样本（空语料 = 零保护，必须显式失败）。"""
        papers = get_golden_papers()
        assert papers, (
            "test_data/expected/ 下没有任何有效基线。"
            "请运行 `python scripts/make_golden_corpus.py` 生成。"
        )

    def test_no_undeclared_gap(self):
        """每份 test_data 里的 PDF 要么有基线，要么在 KNOWN_UNSUPPORTED 里登记了原因。"""
        covered = {pdf.stem for pdf, _ in get_golden_papers()}
        undeclared = [
            p.stem for p in _all_pdfs()
            if p.stem not in covered and p.stem not in KNOWN_UNSUPPORTED
        ]
        assert not undeclared, (
            f"以下样本既无基线也未登记原因：{undeclared}。"
            "请运行 `python scripts/make_golden_corpus.py`，或在 KNOWN_UNSUPPORTED 里补原因。"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "pdf_path,expected_dir",
        _paper_params(),
        ids=lambda p: getattr(p, "stem", str(p)),
    )
    def test_question_count(self, pdf_path, expected_dir):
        expected = json.loads(
            (expected_dir / "question_count.json").read_text(encoding="utf-8")
        )["count"]
        actual = _result_for(pdf_path).question_count
        assert actual >= expected * 0.9, (
            f"{pdf_path.name}: 切题数从基线 {expected} 掉到 {actual}（允许 10% 波动）"
        )

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "pdf_path,expected_dir",
        _paper_params(),
        ids=lambda p: getattr(p, "stem", str(p)),
    )
    def test_question_numbers_contiguous(self, pdf_path, expected_dir):
        """题号必须是 1..N 连续：捕捉漏题、重复题与编号重排回归。"""
        numbers = sorted(q.question_number for q in _result_for(pdf_path).questions)
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"{pdf_path.name}: 题号不连续 → {numbers}"
        )
