from __future__ import annotations

from pathlib import Path


class RapidOCREngine:
    """RapidOCR 的轻量适配器；模型完全在本机运行。"""

    name = "rapidocr_onnxruntime"

    def __init__(self) -> None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError("未安装 rapidocr_onnxruntime，请安装 OCR 可选依赖。") from exc
        self._engine = RapidOCR()

    def recognize(self, image_path: Path) -> tuple[str, float]:
        result, _elapsed = self._engine(str(image_path))
        if not result:
            return "", 0.0
        lines: list[str] = []
        scores: list[float] = []
        for item in result:
            if len(item) < 3:
                continue
            lines.append(str(item[1]))
            scores.append(float(item[2]))
        confidence = sum(scores) / len(scores) if scores else 0.0
        return "\n".join(lines), round(confidence, 4)


def load_ocr_engine(mode: str):
    if mode == "none":
        return None
    if mode in {"auto", "rapidocr"}:
        try:
            return RapidOCREngine()
        except RuntimeError:
            if mode == "rapidocr":
                raise
            return None
    raise ValueError(f"未知 OCR 引擎：{mode}")

