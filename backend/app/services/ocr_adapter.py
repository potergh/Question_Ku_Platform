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
        # For multiple-choice: use stem (options separated) as content
        content = self._build_markdown_content(ocr_question, document_dir)

        # Raw OCR content = original selected text (never modified)
        text_data = ocr_question.get("text", {})
        if isinstance(text_data, dict):
            raw_content = text_data.get("selected", "") or text_data.get("native", "") or text_data.get("local_ocr", "")
        elif isinstance(text_data, str):
            raw_content = text_data
        else:
            raw_content = content

        # Options: extract from content.options (dict) and convert to list
        options = self._extract_options(ocr_question)

        # Content-aware type correction:
        # If section header says "choice" but no options found → reclassify
        # If section header says "fill" but options found → reclassify
        q_type = _correct_question_type(q_type, content, options)

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

    def _extract_options(self, ocr_question: dict) -> list[dict]:
        """Extract options from OCR output and convert to list format.

        Handles both:
        - content.options: {"A": "...", "B": "..."} (from parse_content)
        - options: [{"label": "A", "content": "..."}] (already in list format)
        """
        # Try content.options first (from parse_content in structure.py)
        content_data = ocr_question.get("content", {})
        if isinstance(content_data, dict) and content_data.get("options"):
            opts = content_data["options"]
            if isinstance(opts, dict):
                return [
                    {"label": label, "content": value or ""}
                    for label, value in sorted(opts.items())
                ]
            elif isinstance(opts, list):
                return opts

        # Fallback: top-level options
        top_opts = ocr_question.get("options", [])
        if isinstance(top_opts, list):
            return top_opts

        return []

    def _build_markdown_content(self, ocr_question: dict, document_dir: Path) -> str:
        """Build Markdown canonical content from OCR structured data.

        For multiple-choice questions: use content.stem (options already separated).
        For other questions: use text.selected (full OCR text).
        Images are inlined as ![figure](asset://path).
        """
        # Prefer content.stem (parsed stem with options separated)
        content_data = ocr_question.get("content", {})
        if isinstance(content_data, dict) and content_data.get("stem"):
            content = content_data["stem"]
        else:
            # Fallback to raw text
            text_data = ocr_question.get("text", {})
            if isinstance(text_data, dict):
                content = text_data.get("selected", "") or text_data.get("native", "") or text_data.get("local_ocr", "")
            elif isinstance(text_data, str):
                content = text_data
            else:
                content = ""

        # Inline figures into content at appropriate positions
        # V1: append figures at the end (OCR doesn't provide position info)
        figures = ocr_question.get("assets", {}).get("figures", [])
        if figures:
            figure_md = "\n\n".join(f"![figure](asset://{f})" for f in figures)
            content = f"{content}\n\n{figure_md}" if content else figure_md

        return content.strip()


def _correct_question_type(original_type: str | None, content: str, options: list[dict]) -> str | None:
    """Correct question type based on actual content, not just section headers.

    Rules:
    - Has options (A/B/C/D) → must be choice type (single or multiple)
    - No options + was choice type → reclassify to fill_blank or comprehensive
    - Content has blanks like ___ or （  ）→ likely fill_blank
    - Content is long with sub-questions → likely comprehensive
    """
    has_options = bool(options and len(options) >= 2)

    if has_options:
        # Has options → must be a choice question
        if original_type in ("fill_blank", "comprehensive", "experiment", "calculation", "short_answer", "essay"):
            # Section header was wrong but content has options → it's a choice question
            # Distinguish single vs multiple by looking for hints
            return "single_choice"  # default; AI tagging can refine to multiple_choice
        return original_type or "single_choice"

    # No options
    if original_type in ("single_choice", "multiple_choice"):
        # Section header said "choice" but no options found → reclassify
        # Check for fill-blank indicators
        fill_indicators = ["___", "＿＿＿", "（  ）", "(  )", "（）", "()"]
        has_fill_hint = any(ind in content for ind in fill_indicators)
        if has_fill_hint:
            return "fill_blank"
        # Check for comprehensive indicators (multi-part, long content)
        if any(kw in content for kw in ["（1）", "(1)", "①", "解：", "证明："]):
            return "comprehensive"
        # Default: if content is long, comprehensive; otherwise fill_blank
        if len(content) > 150:
            return "comprehensive"
        return "fill_blank"

    return original_type or "unknown"


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
