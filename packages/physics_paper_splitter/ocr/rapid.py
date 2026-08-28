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

    def recognize_lines(self, image_path: Path) -> list[tuple[list, str, float]]:
        """识别图片，返回带坐标的行级结果 [(四角框像素坐标, 文字, 置信度)]。"""
        result, _elapsed = self._engine(str(image_path))
        lines: list[tuple[list, str, float]] = []
        if not result:
            return lines
        for item in result:
            if len(item) < 3:
                continue
            lines.append((item[0], str(item[1]), float(item[2])))
        return lines

    def recognize(self, image_path: Path) -> tuple[str, float]:
        lines = self.recognize_lines(image_path)
        if not lines:
            return "", 0.0
        text_lines = [item[1] for item in lines]
        confidence = sum(item[2] for item in lines) / len(lines)
        return "\n".join(text_lines), round(confidence, 4)


class PaddleOCREngine:
    """PaddleOCR 引擎 — 对中文数学公式识别优于 RapidOCR。

    PaddleOCR 使用 PP-OCRv4 模型，支持中英混合识别，
    对数学符号（x, y, √, ×, ≤ 等）的识别显著优于 RapidOCR。
    """

    name = "paddleocr"

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError("未安装 paddleocr，请运行: pip install paddlepaddle paddleocr") from exc
        # use_angle_cls=True 支持旋转文字检测
        # lang="ch" 启用中英混合模型
        self._engine = PaddleOCR(use_angle_cls=True, lang="ch")

    def recognize_lines(self, image_path: Path) -> list[tuple[list, str, float]]:
        """识别图片，返回带坐标的行级结果 [(四角框像素坐标, 文字, 置信度)]。"""
        result = self._engine.ocr(str(image_path), cls=True)
        lines: list[tuple[list, str, float]] = []
        if not result or not result[0]:
            return lines
        for line_group in result[0]:
            if len(line_group) < 2:
                continue
            lines.append((line_group[0], str(line_group[1][0]), float(line_group[1][1])))
        return lines

    def recognize(self, image_path: Path) -> tuple[str, float]:
        lines = self.recognize_lines(image_path)
        if not lines:
            return "", 0.0
        text_lines = [item[1] for item in lines]
        confidence = sum(item[2] for item in lines) / len(lines)
        return "\n".join(text_lines), round(confidence, 4)


def load_ocr_engine(mode: str):
    """加载 OCR 引擎。

    mode:
        "auto"     — 优先 PaddleOCR，回退 RapidOCR，再回退 None
        "paddleocr" — 强制 PaddleOCR（缺失则报错）
        "rapidocr"  — 强制 RapidOCR（缺失则报错）
        "none"      — 不使用 OCR
    """
    if mode == "none":
        return None

    if mode == "paddleocr":
        return PaddleOCREngine()

    if mode == "rapidocr":
        return RapidOCREngine()

    if mode == "auto":
        # 优先 RapidOCR（稳定）；PaddleOCR 3.x 有兼容性问题，待修复后启用
        try:
            return RapidOCREngine()
        except RuntimeError:
            pass
        # 回退尝试 PaddleOCR
        try:
            return PaddleOCREngine()
        except RuntimeError:
            return None

    raise ValueError(f"未知 OCR 引擎：{mode}")
