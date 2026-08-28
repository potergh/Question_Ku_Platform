from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PageInspection:
    page_index: int
    width: float
    height: float
    text_chars: int
    image_count: int
    replacement_chars: int
    question_numbers: list[int] = field(default_factory=list)
    is_answer_page: bool = False
    needs_ocr: bool = False


@dataclass(slots=True)
class DocumentInspection:
    pdf_path: Path
    page_count: int
    question_page_count: int
    answer_start_page: int | None
    pages: list[PageInspection]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pdf_path"] = str(self.pdf_path)
        return data


@dataclass(slots=True, frozen=True)
class QuestionAnchor:
    number: int
    page_index: int
    y: float
    matched_text: str


@dataclass(slots=True)
class CropSegment:
    page_index: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(slots=True)
class QuestionRecord:
    number: int
    filename: str
    start_page: int
    end_page: int
    is_cross_page: bool
    segments: list[CropSegment]
    width_px: int = 0
    height_px: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

