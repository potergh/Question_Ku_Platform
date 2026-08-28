from __future__ import annotations

import json
import shutil
from pathlib import Path

import pymupdf as fitz

from .answers import parse_answers
from .cropper import QuestionCropper
from .figures import FigureExtractor
from .inspector import PDFInspector
from .ocr import QuestionTextPipeline
from .quality import CompletenessValidator
from .scan import ensure_text_layer
from .splitter import QuestionSplitter


class SplitPipeline:
    def __init__(self, dpi: int = 300, webp_quality: int = 92, ocr_engine: str = "auto"):
        self.inspector = PDFInspector()
        self.splitter = QuestionSplitter()
        self.cropper = QuestionCropper(dpi=dpi, webp_quality=webp_quality)
        self.figures = FigureExtractor(dpi=dpi, webp_quality=webp_quality)
        self.text_pipeline = QuestionTextPipeline(engine_mode=ocr_engine)
        self.completeness = CompletenessValidator()

    def process(self, pdf_path: Path, output_root: Path, document_name: str | None = None) -> dict:
        document_name = document_name or pdf_path.stem
        if not document_name or Path(document_name).name != document_name:
            raise ValueError(f"非法输出目录名：{document_name!r}")
        document_dir = output_root / document_name
        question_dir = document_dir / "questions"
        document_dir.mkdir(parents=True, exist_ok=True)

        # questions/ 与 figures/ 完全由本程序管理。重复处理同一份试卷时先清理
        # 这两个目录，避免上次运行遗留的高题号图片混入本次结果。
        for generated_dir in (question_dir, document_dir / "figures"):
            if generated_dir.exists():
                shutil.rmtree(generated_dir)

        # 扫描件没有文字层，先整页 OCR 补一层隐形文字，后续流程不变。
        effective_pdf = ensure_text_layer(
            pdf_path, document_dir / "_ocr_layer.pdf", self.text_pipeline.engine
        )
        inspection = self.inspector.inspect(effective_pdf)

        with fitz.open(effective_pdf) as doc:
            anchors = self.splitter.find_anchors(doc, inspection)
            records = self.splitter.build_records(doc, inspection, anchors)
            for record in records:
                self.cropper.crop(doc, record, question_dir)
            qa = self.completeness.validate(records, question_dir)
            figures_map = self.figures.extract_all(doc, records, document_dir / "figures")
            answers = parse_answers(doc, inspection)
            questions = self.text_pipeline.process(
                doc,
                records,
                question_dir,
                pdf_path,
                figures_map=figures_map,
                answers_map=answers["questions"],
            )

        numbers = [record.number for record in records]
        expected = list(range(1, max(numbers, default=0) + 1))
        warnings = list(inspection.warnings)
        if numbers != expected:
            missing = sorted(set(expected) - set(numbers))
            warnings.append(f"题号不连续，缺失：{missing}")
        if not records:
            warnings.append("没有识别到题号；可能是扫描版 PDF，需要 OCR。")
        answer_missing = sorted(set(numbers) - set(answers["questions"]))
        if numbers and answer_missing:
            warnings.append(f"答案页未匹配到题目：{answer_missing}")
        answers["missing_numbers"] = answer_missing
        answers["matched_count"] = len(set(numbers) & set(answers["questions"]))

        manifest = {
            "schema_version": 2,
            "source_pdf": str(pdf_path.resolve()),
            "output_dir": str(document_dir.resolve()),
            "question_count": len(records),
            "question_numbers": numbers,
            "cross_page_questions": [record.number for record in records if record.is_cross_page],
            "figure_count": sum(len(paths) for paths in figures_map.values()),
            "answer_matched_count": answers["matched_count"],
            "warnings": warnings,
            "questions": [record.to_dict() for record in records],
        }
        self._write_json(document_dir / "inspection.json", inspection.to_dict())
        self._write_json(document_dir / "manifest.json", manifest)
        self._write_json(document_dir / "qa.json", qa)
        self._write_json(document_dir / "questions.json", questions)
        self._write_json(document_dir / "answers.json", answers)
        return manifest

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_pdfs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".pdf" else []
    return sorted(input_path.rglob("*.pdf"))
