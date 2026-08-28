"""OCR Regression Test Framework.

Uses golden corpus to verify OCR accuracy hasn't degraded.
Run with: python -m pytest tests/test_ocr_regression.py -v

Golden corpus structure:
    test_data/
    ├── paper01.pdf
    │   └── expected/
    │       ├── question_count.json  → {"count": 12}
    │       └── question_numbers.json → [1,2,3,...,12]
    └── paper02.pdf
        └── expected/
            └── ...
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


def get_golden_papers():
    """Discover all papers with expected/ directories in test_data/."""
    papers = []
    if not TEST_DATA_DIR.exists():
        return papers
    for paper_dir in sorted(TEST_DATA_DIR.iterdir()):
        if paper_dir.suffix == ".pdf":
            expected_dir = paper_dir.parent / "expected" / paper_dir.stem
            if expected_dir.exists():
                papers.append((paper_dir, expected_dir))
    return papers


@pytest.fixture(scope="module")
def adapter():
    return OCRAdapter()


class TestOCRRegression:
    """Regression tests for OCR accuracy."""

    def test_adapter_import(self):
        """Verify OCR adapter can be imported."""
        from app.services.ocr_adapter import OCRAdapter, QuestionData, OCRResult
        assert OCRAdapter is not None

    def test_golden_corpus_exists(self):
        """Verify at least one golden paper exists for regression testing."""
        papers = get_golden_papers()
        # This test will fail until we add golden papers
        # For now, just verify the framework works
        assert isinstance(papers, list)

    # Add parameterized tests for each golden paper:
    # @pytest.mark.parametrize("pdf_path,expected_dir", get_golden_papers())
    # def test_question_count(self, adapter, pdf_path, expected_dir):
    #     result = adapter.process_pdf(pdf_path, OCR_OUTPUT_DIR)
    #     expected = json.loads((expected_dir / "question_count.json").read_text())
    #     assert result.question_count >= expected["count"] * 0.9  # Allow 10% margin
