"""OCR Adapter — bridges physics_paper_splitter output to platform Question model.

This is the ONLY layer that knows about the OCR package internals.
The rest of the platform never imports from physics_paper_splitter directly.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Add packages/ to sys.path so physics_paper_splitter is importable
# WITHOUT modifying the OCR source code.
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "packages"
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from physics_paper_splitter.pipeline import SplitPipeline  # noqa: E402


@dataclass
class QuestionData:
    """Platform-neutral question data from OCR.

    The adapter converts OCR output into this format.
    The service layer then maps QuestionData → SQLAlchemy Question model.
    """

    source_question_id: str  # e.g. "Q001"
    question_number: int
    question_type: str | None  # 选择题/填空题/解答题/...
    raw_ocr_content: str  # Original OCR text, NEVER modified by user edits
    content: str  # Markdown canonical (images inline, LaTeX $...$)
    options: list[dict]  # [{"label": "A", "content": "..."}]
    answer: str | None
    explanation: str | None
    score: float | None
    card_image_path: str | None  # Path to question card image (webp)
    ocr_confidence: float | None
    needs_review: bool


class OCRAdapter:
    """Adapter between physics_paper_splitter and the platform."""

    def __init__(self, dpi: int = 300, webp_quality: int = 92, ocr_engine: str = "auto"):
        self.pipeline = SplitPipeline(dpi=dpi, webp_quality=webp_quality, ocr_engine=ocr_engine)

    def process_pdf(self, pdf_path: Path, output_dir: Path, document_name: str | None = None) -> OCRResult:
        """Run OCR pipeline and convert output to platform format.

        Args:
            pdf_path: Path to the uploaded PDF file.
            output_dir: Where to write OCR output (data/ocr_output/).
            document_name: Optional name for the output directory.

        Returns:
            OCRResult with manifest info and list of QuestionData.
        """
        document_name = document_name or pdf_path.stem
        manifest = self.pipeline.process(pdf_path, output_dir, document_name)

        # Read questions.json produced by the pipeline
        document_dir = output_dir / document_name
        questions_json_path = document_dir / "questions.json"
        questions_raw = json.loads(questions_json_path.read_text(encoding="utf-8"))

        # Handle both dict format (with 'questions' key) and legacy list format
        if isinstance(questions_raw, dict):
            questions_list = questions_raw.get("questions", [])
        elif isinstance(questions_raw, list):
            questions_list = questions_raw
        else:
            questions_list = []

        # Convert to platform QuestionData
        question_data_list = []
        for q in questions_list:
            qd = self._convert_question(q, document_dir)
            question_data_list.append(qd)

        return OCRResult(
            manifest=questions_raw if isinstance(questions_raw, dict) else {},
            questions=question_data_list,
            output_dir=document_dir,
        )

    def _convert_question(self, ocr_question: dict, document_dir: Path) -> QuestionData:
        """Convert a single OCR question dict to QuestionData."""
        q_id = ocr_question.get("id", "")
        q_number = ocr_question.get("number", 0)
        q_type = ocr_question.get("type")

        # Build Markdown canonical content from OCR output
        # The OCR pipeline provides structured fields; we merge them into Markdown
        content = self._build_markdown_content(ocr_question, document_dir)
        raw_content = content  # V1: raw = content (no separate raw pipeline)

        # Options for multiple choice
        options = ocr_question.get("options", [])

        # Answer and explanation
        answer_data = ocr_question.get("answer", {})
        answer = answer_data.get("content") if isinstance(answer_data, dict) else str(answer_data) if answer_data else None
        explanation = ocr_question.get("explanation")

        # Score
        score = ocr_question.get("score")

        # Card image path
        card_image = ocr_question.get("assets", {}).get("card")
        card_image_path = str(document_dir / card_image) if card_image else None

        # Confidence / review
        quality = ocr_question.get("quality", {})
        confidence = quality.get("confidence") if isinstance(quality, dict) else None
        needs_review = quality.get("needs_review", True) if isinstance(quality, dict) else True

        return QuestionData(
            source_question_id=str(q_id),
            question_number=q_number,
            question_type=q_type,
            raw_ocr_content=raw_content,
            content=content,
            options=options,
            answer=answer,
            explanation=explanation,
            score=score,
            card_image_path=card_image_path,
            ocr_confidence=confidence,
            needs_review=needs_review,
        )

    def _build_markdown_content(self, ocr_question: dict, document_dir: Path) -> str:
        """Build Markdown canonical content from OCR structured data.

        Images are inlined as ![figure](asset://path).
        LaTeX formulas are wrapped in $...$.
        """
        # The OCR pipeline provides content in different formats
        # Try to use the best available text
        text_data = ocr_question.get("text", {})
        if isinstance(text_data, dict):
            content = text_data.get("selected", "") or text_data.get("native", "") or text_data.get("local_ocr", "")
        elif isinstance(text_data, str):
            content = text_data
        else:
            content = ""

        # If there's a content field directly
        if not content:
            content = ocr_question.get("content", {}).get("stem", "") if isinstance(ocr_question.get("content"), dict) else ""

        # Inline figures into content at appropriate positions
        # V1: append figures at the end (OCR doesn't provide position info)
        figures = ocr_question.get("assets", {}).get("figures", [])
        if figures:
            figure_md = "\n\n".join(f"![figure](asset://figures/{f})" for f in figures)
            content = f"{content}\n\n{figure_md}" if content else figure_md

        return content.strip()


@dataclass
class OCRResult:
    """Result from OCR processing."""

    manifest: dict  # Pipeline manifest (question_count, numbers, warnings, etc.)
    questions: list[QuestionData]
    output_dir: Path

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def warnings(self) -> list[str]:
        return self.manifest.get("warnings", [])
