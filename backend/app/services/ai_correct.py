"""AI question correction service — LLM-powered OCR content refinement.

Hybrid approach:
1. Deterministic pre-processing (no LLM) — fix what we can cheaply
2. Problem analysis — determine if LLM is needed
3. LLM correction — send image + text for intelligent fix
4. Post-processing — validate and normalize output
"""

import base64
import json
import logging
import re
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_service import _call_llm, AIServiceError

logger = logging.getLogger(__name__)

# ── Default prompt (stored in Settings.ai_review_prompt, editable by user) ──

DEFAULT_REVIEW_PROMPT = """你是一位教学助理，负责修正 OCR 识别的考试题目。

修正规则：
1. 修复乱码和识别错误（参考图片推断正确的符号、公式、文字）
2. 数学公式用 $...$ 包裹（行内公式），复杂公式用 $$...$$ 包裹。注意：必须用 $ 符号，不要用 \( \) 或 \[ \]
3. 选择题选项整理为 A. B. C. D. 格式，每行一个
4. 表格内容用 Markdown 表格语法
5. 横线/分隔线用 --- 表示
6. 去除页眉页脚（如“第X页”、试卷标题等无关内容）
7. 保持图片引用 ![...](...) 不变
8. 保持题目原意不变，只修正排版和识别错误

重要 — 字段分离规则：
- content 只包含“题目本身”（已知条件、问题描述），绝对不要包含选项 A/B/C/D
- 选项必须只放在 options 数组中，不要同时出现在 content 里
- answer 只包含最终答案（如“A”“D”“-8”等）
- explanation 包含完整的解题过程和推导步骤

返回 JSON 格式（不要其他文字）：
{
  "content": "修正后的题目内容（仅题目，不含选项、不含解答）",
  "options": [{"label": "A", "content": "选项内容"}, ...],
  "answer": "最终答案（如 A、D 等）",
  "explanation": "解题过程（如有）"
}

如果没有选项（非选择题），options 返回空数组 []。"""

# ── Subject display names ──

_SUBJECT_NAMES = {
    "physics": "物理", "math": "数学", "chemistry": "化学",
    "english": "英语",
}


# ── Deterministic pre-processing ─────────────────────────────────────

def _deterministic_cleanup(text: str) -> str:
    """Fix common OCR issues without LLM."""
    if not text:
        return text

    # Remove page footers
    text = re.sub(r"第\s*\d+\s*页[（(]共\s*\d+\s*页[）)]", "", text)
    text = re.sub(r"第\s*\d+\s*页", "", text)

    # Collapse 3+ newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove trailing whitespace per line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)

    # Replace common OCR artifacts
    text = text.replace("\ufffd", "")  # Remove replacement chars
    text = text.replace("□", "")       # Remove empty boxes

    # Fix fullwidth punctuation
    text = text.replace("﹣", "-")
    text = text.replace("＝", "=")

    return text.strip()


def _analyze_problems(content: str, options: list | None) -> dict:
    """Analyze what's wrong with the OCR content. Returns problem summary."""
    problems = []
    severity = "good"  # good / needs_fix / needs_ai

    if not content or len(content.strip()) < 10:
        problems.append("内容为空或过短")
        severity = "needs_ai"

    # Check garbled chars (should be cleaned already, but check original)
    garbled = content.count("\ufffd")
    if garbled > 0:
        problems.append(f"含 {garbled} 个乱码字符")
        severity = "needs_ai"

    # Check options
    if options:
        empty_opts = [o for o in options if not o.get("content", "").strip()]
        if empty_opts:
            problems.append(f"{len(empty_opts)} 个选项内容为空")
            severity = "needs_ai"
    else:
        # Check if content has option-like patterns that weren't parsed
        opt_pattern = re.findall(r"(?:^|\s)([A-D])\s*[\.．、]", content)
        if len(opt_pattern) >= 2:
            problems.append("选项未被正确解析")
            severity = "needs_ai"

    # Check for math formulas not wrapped in $
    math_like = re.findall(r"\d+[xXyYzZ]\s*[-+=]", content)
    if math_like:
        problems.append("数学公式未用 LaTeX 格式")
        if severity == "good":
            severity = "needs_fix"

    # Check for mixed line breaks (OCR splitting single line into multiple)
    lines = content.split("\n")
    short_lines = [l for l in lines if 0 < len(l.strip()) < 5]
    if len(short_lines) > len(lines) * 0.3:
        problems.append("文本行被错误拆分")
        if severity == "good":
            severity = "needs_fix"

    return {
        "severity": severity,
        "problems": problems,
        "needs_llm": severity == "needs_ai",
    }


# ── Image encoding ────────────────────────────────────────────────────

def _encode_card_image(image_path: str | None) -> str | None:
    """Read card image and encode as base64 data URI for multimodal LLM."""
    if not image_path:
        return None
    p = Path(image_path)
    if not p.exists():
        return None
    try:
        data = p.read_bytes()
        # Limit to 4MB to avoid token explosion
        if len(data) > 4 * 1024 * 1024:
            logger.warning(f"Card image too large ({len(data)} bytes): {p}")
            return None
        suffix = p.suffix.lower().lstrip(".")
        if suffix not in ("png", "jpg", "jpeg", "webp", "gif"):
            suffix = "png"
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/{suffix};base64,{b64}"
    except Exception as e:
        logger.warning(f"Failed to encode card image: {e}")
        return None


# ── Post-processing: strip options from content ─────────────────────

def _strip_options_from_content(content: str, options: list) -> str:
    """Remove option lines (A. xxx, B. xxx, etc.) from content to avoid duplication."""
    if not content or not options:
        return content

    lines = content.split("\n")
    # Build set of option content strings for matching
    opt_contents = set()
    for opt in options:
        if isinstance(opt, dict):
            c = opt.get("content", "").strip()
            if c:
                opt_contents.add(c)
                # Also add variants without LaTeX wrappers
                opt_contents.add(c.replace("$", ""))

    # Also match lines starting with option labels
    opt_labels = set()
    for opt in options:
        if isinstance(opt, dict):
            opt_labels.add(opt.get("label", ""))

    cleaned = []
    skip_section = False
    for line in lines:
        stripped = line.strip()

        # Skip lines that are purely an option (e.g. "A. $1+x^2=91$")
        is_option_line = False
        for label in opt_labels:
            if stripped.startswith(f"{label}.") or stripped.startswith(f"{label} "):
                is_option_line = True
                break
            # Also match Chinese-style: "A．xxx"
            if stripped.startswith(f"{label}\uff0e"):
                is_option_line = True
                break

        if is_option_line:
            skip_section = True
            continue

        # Skip "选项" header line
        if stripped in ("选项",):
            skip_section = True
            continue

        # If we were in option section and hit a non-option line, resume
        if skip_section and stripped and not is_option_line:
            # Check if this line looks like it's back to normal content
            # (not an option continuation)
            skip_section = False

        if not skip_section:
            cleaned.append(line)

    result = "\n".join(cleaned).strip()
    # Collapse multiple blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


# ── Main correction function ──────────────────────────────────────────

async def correct_question(
    db: AsyncSession,
    content: str,
    options: list | None = None,
    answer: str | None = None,
    explanation: str | None = None,
    subject: str | None = None,
    card_image_path: str | None = None,
    custom_prompt: str | None = None,
) -> dict:
    """AI-correct a single question's OCR content.

    Returns dict with: {content, options, answer, explanation, analysis, needs_llm}
    """
    from app.models.settings import Settings
    from sqlalchemy import select

    # Step 1: Deterministic cleanup
    cleaned = _deterministic_cleanup(content)

    # Step 2: Analyze problems
    analysis = _analyze_problems(cleaned, options)

    # If content is good and no options to fix, return as-is
    if not analysis["needs_llm"]:
        return {
            "content": cleaned,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "analysis": analysis,
            "needs_llm": False,
        }

    # Step 3: Call LLM for intelligent correction
    # Get prompt (custom or from DB or default)
    prompt = custom_prompt
    if not prompt:
        result = await db.execute(select(Settings).where(Settings.id == 1))
        settings = result.scalar_one_or_none()
        prompt = (settings and settings.ai_review_prompt) or DEFAULT_REVIEW_PROMPT

    # Add subject context
    subject_name = _SUBJECT_NAMES.get(subject, subject or "未知学科")
    system_msg = f"【当前学科：{subject_name}】\n\n{prompt}"

    # Build user message with image
    user_content = []

    # Add card image if available
    image_uri = _encode_card_image(card_image_path)
    if image_uri:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": image_uri},
        })

    # Add text
    text_parts = [f"原始 OCR 内容：\n{cleaned}"]
    if options:
        opt_text = "\n".join(
            f"{o.get('label', chr(65+i))}. {o.get('content', '')}"
            for i, o in enumerate(options)
        )
        text_parts.append(f"\n当前选项：\n{opt_text}")
    if answer:
        text_parts.append(f"\n当前答案：{answer}")

    user_content.append({"type": "text", "text": "\n".join(text_parts)})

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]

    try:
        # Longer timeout for image-based requests
        req_timeout = 120 if image_uri else 60
        response = await _call_llm(db, messages, temperature=0.2, timeout=req_timeout)
    except AIServiceError as e:
        logger.warning(f"AI correction failed: {e}")
        return {
            "content": cleaned,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "analysis": {**analysis, "error": str(e)},
            "needs_llm": True,
        }

    # Step 4: Parse LLM response
    try:
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        corrected = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"AI correction response not JSON: {response[:200]}")
        return {
            "content": cleaned,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "analysis": {**analysis, "error": "AI 返回格式错误"},
            "needs_llm": True,
        }

    # Validate and merge
    result_content = corrected.get("content", cleaned)
    result_options = corrected.get("options")
    result_answer = corrected.get("answer") or answer
    result_explanation = corrected.get("explanation") or explanation

    # Normalize options format
    if result_options and isinstance(result_options, list):
        normalized = []
        for i, opt in enumerate(result_options):
            if isinstance(opt, dict):
                label = opt.get("label", chr(65 + i))
                normalized.append({"label": label, "content": opt.get("content", "")})
            elif isinstance(opt, str):
                normalized.append({"label": chr(65 + i), "content": opt})
        result_options = normalized
    else:
        result_options = options

    # Post-process: strip option lines from content to avoid duplication
    if result_options and isinstance(result_options, list):
        result_content = _strip_options_from_content(result_content, result_options)

    return {
        "content": result_content,
        "options": result_options,
        "answer": result_answer,
        "explanation": result_explanation,
        "analysis": analysis,
        "needs_llm": True,
    }
