from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from .models import QuestionRecord


@dataclass(slots=True)
class CardQAResult:
    number: int
    status: str
    edge_touch: list[str]
    warnings: list[str]


class CompletenessValidator:
    """检查题卡是否为空、是否贴边截断，以及题号序列是否连续。"""

    def __init__(self, ink_threshold: int = 235, edge_width: int = 3):
        self.ink_threshold = ink_threshold
        self.edge_width = edge_width

    def validate(self, records: list[QuestionRecord], question_dir: Path) -> dict:
        numbers = [record.number for record in records]
        expected = list(range(1, max(numbers, default=0) + 1))
        results: list[CardQAResult] = []

        for record in records:
            path = question_dir / record.filename
            warnings: list[str] = []
            edge_touch: list[str] = []
            if not path.exists() or path.stat().st_size == 0:
                warnings.append("题卡文件不存在或为空。")
            else:
                with Image.open(path) as image:
                    gray = image.convert("L")
                    width, height = gray.size
                    if width < 300 or height < 80:
                        warnings.append("题卡尺寸异常小。")
                    strips = {
                        "left": (0, 0, min(self.edge_width, width), height),
                        "right": (max(0, width - self.edge_width), 0, width, height),
                        "top": (0, 0, width, min(self.edge_width, height)),
                        "bottom": (0, max(0, height - self.edge_width), width, height),
                    }
                    for name, box in strips.items():
                        extrema = gray.crop(box).getextrema()
                        if extrema[0] < self.ink_threshold:
                            edge_touch.append(name)
                    if edge_touch:
                        warnings.append("内容触及图片边缘，可能存在截断，需复核。")

            results.append(
                CardQAResult(
                    number=record.number,
                    status="review" if warnings else "pass",
                    edge_touch=edge_touch,
                    warnings=warnings,
                )
            )

        review = [result.number for result in results if result.status == "review"]
        return {
            "question_count": len(records),
            "number_sequence_ok": numbers == expected,
            "missing_numbers": sorted(set(expected) - set(numbers)),
            "pass_count": len(records) - len(review),
            "review_count": len(review),
            "review_questions": review,
            "all_cards_present": all((question_dir / record.filename).exists() for record in records),
            "results": [asdict(result) for result in results],
        }

