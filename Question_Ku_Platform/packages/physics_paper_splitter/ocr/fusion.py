from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# 数字 + 紧邻单位字符；允许单位中的 ASCII 次方数字，后续与白名单比对。
NUMBER_TOKEN_RE = re.compile(r"(\d+(?:[\.．]\d+)?)\s*([A-Za-z0-9Ω℃³²/%]{0,8})")
# 小数点后直接跟字母：典型数字误识别（0.6A 被读成 0.GA）。
SUSPICIOUS_DECIMAL_RE = re.compile(r"\d\.[A-Za-z]")
# 单位重复书写：100VV、220AA。
DUPLICATED_UNIT_RE = re.compile(r"(\d+(?:[\.．]\d+)?)\s*([A-Za-zΩ]{1,3})\2(?![A-Za-z])")

PHYSICS_UNITS = {
    "V", "A", "Ω", "W", "J", "N", "Pa", "Hz", "kg", "g", "mg",
    "m", "cm", "mm", "km", "mL", "L", "s", "h", "min",
    "m²", "cm²", "m³", "cm³", "m/s", "m/s²", "km/h", "kg/m³", "g/cm³", "℃", "%",
}

# ASCII 上标写法 → 规范上标；只提示不改写。
UNIT_VARIANTS = {
    "kg/m3": "kg/m³",
    "g/cm3": "g/cm³",
    "m3": "m³",
    "cm3": "cm³",
    "m2": "m²",
    "cm2": "cm²",
    "m/s2": "m/s²",
}

REVIEW_THRESHOLD = 0.85


@dataclass(slots=True)
class FusionResult:
    number_conflicts: list[dict] = field(default_factory=list)
    unit_warnings: list[str] = field(default_factory=list)
    needs_formula: bool = False
    formula_lines: list[str] = field(default_factory=list)
    agreement: float | None = None
    review_score: float = 1.0
    needs_review: bool = False

    def to_dict(self) -> dict:
        return {
            "number_conflicts": self.number_conflicts,
            "unit_warnings": self.unit_warnings,
            "needs_formula": self.needs_formula,
            "formula_lines": self.formula_lines,
            "agreement": self.agreement,
            "review_score": self.review_score,
            "needs_review": self.needs_review,
        }


def extract_numeric_tokens(text: str) -> list[tuple[str, str]]:
    """提取 (数字, 单位) token；全角小数点归一化，单位不在这里做合法性判断。"""
    tokens: list[tuple[str, str]] = []
    for match in NUMBER_TOKEN_RE.finditer(text):
        number = match.group(1).replace("．", ".").strip()
        unit = match.group(2).strip()
        tokens.append((number, unit))
    return tokens


def _normalized_physics_tokens(text: str) -> list[tuple[str, str]]:
    """只保留真实物理单位，并统一 ASCII/上标写法。"""
    tokens: list[tuple[str, str]] = []
    for number, unit in extract_numeric_tokens(text):
        canonical = UNIT_VARIANTS.get(unit, unit)
        if canonical in PHYSICS_UNITS:
            tokens.append((number, canonical))
    return tokens


def check_units(text: str) -> list[str]:
    """检测非法或可疑的物理单位写法，只产生警告，不改写原文。"""
    warnings: list[str] = []
    for variant, canonical in UNIT_VARIANTS.items():
        # 前置字符排除字母与斜杠，避免 m3 在 kg/m3 内重复命中。
        if re.search(rf"(?<![A-Za-z/]){re.escape(variant)}(?![A-Za-z0-9])", text):
            warnings.append(f"疑似上标缺失：{variant} 建议写作 {canonical}。")
    for match in DUPLICATED_UNIT_RE.finditer(text):
        warnings.append(f"单位重复书写：{match.group(0)}。")
    for match in SUSPICIOUS_DECIMAL_RE.finditer(text):
        warnings.append(f"疑似数字误识别：{match.group(0)}。")
    return warnings


def _formula_lines(text: str) -> list[str]:
    """含替换字符（□ 或 □）的行视为公式残迹；文本不做任何替换，仅标记。"""
    return [line.strip() for line in text.splitlines() if "\ufffd" in line or "□" in line]


def compare_numeric_tokens(native_text: str, ocr_text: str) -> tuple[list[dict], float]:
    """比对原生文字与 OCR 的数字/单位一致性，返回冲突列表与一致率。"""
    # 只对带单位数值做冲突判定：无单位数字里混有大量题号、分值与图内刻度读数，
    # OCR 会额外读出刻度数字，噪声远大于信号。
    native = _normalized_physics_tokens(native_text)
    ocr = _normalized_physics_tokens(ocr_text)
    native_counter = Counter(native)
    ocr_counter = Counter(ocr)
    intersection = sum((native_counter & ocr_counter).values())
    union = sum((native_counter | ocr_counter).values())
    agreement = round(intersection / union, 4) if union else 1.0

    conflicts: list[dict] = []
    # 同单位且数值集合真正矛盾时才算强冲突。若一侧只是另一侧的子集，
    # 常见原因是 OCR 额外读到了图中刻度，不应强制整题进入人工复核。
    native_by_unit: dict[str, list[str]] = {}
    ocr_by_unit: dict[str, list[str]] = {}
    for number, unit in native:
        native_by_unit.setdefault(unit, []).append(number)
    for number, unit in ocr:
        ocr_by_unit.setdefault(unit, []).append(number)
    for unit in sorted(set(native_by_unit) & set(ocr_by_unit)):
        native_numbers = sorted(set(native_by_unit[unit]))
        ocr_numbers = sorted(set(ocr_by_unit[unit]))
        native_set = set(native_numbers)
        ocr_set = set(ocr_numbers)
        if native_set != ocr_set and not (native_set <= ocr_set or ocr_set <= native_set):
            conflicts.append({"unit": unit, "native": native_numbers, "ocr": ocr_numbers})
    return conflicts, agreement


def fuse(
    native_text: str,
    ocr_text: str,
    native_score: float,
    ocr_confidence: float | None,
) -> FusionResult:
    """融合原生文字与本地 OCR：冲突检测、单位校验、公式标记与综合评分。"""
    result = FusionResult()

    if native_text and ocr_text and ocr_confidence is not None:
        result.number_conflicts, result.agreement = compare_numeric_tokens(native_text, ocr_text)
    result.unit_warnings = check_units(native_text if native_text else ocr_text)
    formula_lines = _formula_lines(native_text if native_text else ocr_text)
    result.formula_lines = formula_lines[:5]
    result.needs_formula = bool(formula_lines)

    if ocr_confidence is None:
        base = native_score
    else:
        base = 0.6 * native_score + 0.4 * ocr_confidence
    penalty = 0.15 if result.number_conflicts else 0.0
    penalty += 0.03 * min(len(result.unit_warnings), 3)
    result.review_score = round(max(0.0, min(1.0, base - penalty)), 4)
    result.needs_review = result.review_score < REVIEW_THRESHOLD or bool(result.number_conflicts)
    return result
