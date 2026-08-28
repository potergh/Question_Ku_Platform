"""AI service — reads config from DB, calls OpenAI-compatible API."""

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Settings

logger = logging.getLogger(__name__)


class AIServiceError(Exception):
    """Raised when AI service is unavailable or misconfigured."""
    pass


async def _get_ai_config(db: AsyncSession) -> dict:
    """Read AI settings from DB. Raises if mode is off."""
    result = await db.execute(select(Settings).where(Settings.id == 1))
    s = result.scalar_one_or_none()
    if not s:
        raise AIServiceError("AI 未配置，请先在设置页面配置")
    if s.ai_mode == "off":
        raise AIServiceError("AI 功能已关闭，请在设置页面开启")

    base_url = s.ai_base_url.rstrip("/")
    if s.ai_mode == "local":
        base_url = "http://localhost:11434/v1"

    return {
        "base_url": base_url,
        "api_key": s.ai_api_key or "ollama",
        "model": s.ai_model,
        "temperature": s.ai_temperature,
    }


async def _call_llm(db: AsyncSession, messages: list[dict], temperature: float | None = None, timeout: float = 60) -> str:
    """Call the LLM API and return the response text."""
    config = await _get_ai_config(db)

    url = f"{config['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": temperature if temperature is not None else config["temperature"],
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.ConnectError as e:
            raise AIServiceError(f"无法连接 AI 服务: {e}")
        except httpx.TimeoutException:
            raise AIServiceError("AI 服务响应超时")

    if resp.status_code != 200:
        raise AIServiceError(f"AI 返回错误 (HTTP {resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ── Public Actions ──────────────────────────────────────────────────


async def auto_tag_question(
    db: AsyncSession,
    content: str,
    options: list | None = None,
    answer: str | None = None,
) -> dict:
    """
    AI auto-tagging for a question: suggest tags, difficulty, question_type.
    Called after OCR to enrich question metadata.
    Returns {"tag_ids": [...], "difficulty": int, "question_type": str, "confidence": float}
    """
    from app.models import Tag

    # Get available tags for reference
    result = await db.execute(select(Tag).order_by(Tag.category, Tag.name))
    tags = result.scalars().all()
    if not tags:
        return {"tag_ids": [], "difficulty": None, "question_type": None, "confidence": 0}

    tag_text = "\n".join([f"ID:{t.id} | {t.category} | {t.name}" for t in tags[:50]])

    # Build question summary
    q_summary = content[:300] if content else ""
    if options:
        opts = [f"{o.get('label','')}. {o.get('content','')}" for o in (options or [])[:6]]
        q_summary += "\n选项: " + "; ".join(opts)
    if answer:
        q_summary += f"\n答案: {answer[:100]}"

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位物理教学专家。分析题目并返回 JSON 格式的标注建议。\n"
                "返回格式：{\"tag_ids\": [\"id1\", \"id2\"], \"difficulty\": 1-5, \"question_type\": \"选择题/填空题/解答题/计算题/实验题\", \"confidence\": 0-1}\n"
                "tag_ids 必须从可用标签中选择，最多选 3 个。只返回 JSON，不要其他文字。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"可用标签：\n{tag_text}\n\n"
                f"题目内容：\n{q_summary}\n\n"
                "请分析并返回标注建议。"
            ),
        },
    ]

    response_text = await _call_llm(db, messages, temperature=0.3)

    # Parse JSON response
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        suggestions = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"AI auto_tag response not JSON: {response_text[:200]}")
        return {"tag_ids": [], "difficulty": None, "question_type": None, "confidence": 0}

    # Validate tag_ids exist
    valid_tag_ids = {t.id for t in tags}
    suggested_ids = [tid for tid in suggestions.get("tag_ids", []) if tid in valid_tag_ids][:3]

    return {
        "tag_ids": suggested_ids,
        "difficulty": suggestions.get("difficulty"),
        "question_type": suggestions.get("question_type"),
        "confidence": suggestions.get("confidence", 0.5),
    }


async def auto_tag_questions_batch(
    db: AsyncSession,
    questions: list[dict],
) -> list[dict]:
    """
    Batch AI auto-tagging for multiple questions in one LLM call.
    questions: list of {"id": str, "content": str, "options": list, "answer": str}
    Returns list of {"id": str, "tag_ids": [...], "difficulty": int, "question_type": str, "confidence": float}
    """
    from app.models import Tag

    if not questions:
        return []

    # Get subjects of selected questions
    subjects = set()
    for q in questions:
        if q.get("subject"):
            subjects.add(q["subject"])

    # Get available tags filtered by subjects
    query = select(Tag).order_by(Tag.category, Tag.name)
    if subjects:
        query = query.where(Tag.subject.in_(subjects))
    result = await db.execute(query)
    tags = result.scalars().all()
    if not tags:
        return [{"id": q["id"], "tag_ids": [], "difficulty": None, "question_type": None, "confidence": 0} for q in questions]

    tag_text = "\n".join([f"ID:{t.id} | {t.subject}/{t.category} | {t.name}" for t in tags[:80]])

    # Build all questions summary
    q_summaries = []
    for i, q in enumerate(questions):
        summary = f"--- 题目 {i+1} (ID: {q['id']}) ---\n"
        summary += (q.get("content") or "")[:200]
        if q.get("options"):
            opts = [f"{o.get('label','')}. {o.get('content','')}" for o in q["options"][:6]]
            summary += "\n选项: " + "; ".join(opts)
        if q.get("answer"):
            summary += f"\n答案: {(q['answer'] or '')[:80]}"
        q_summaries.append(summary)

    all_q_text = "\n\n".join(q_summaries)

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位教学专家。分析多道题目并返回 JSON 数组格式的标注建议。\n"
                "返回格式：[{\"id\": \"题目ID\", \"tag_ids\": [\"id1\", \"id2\"], \"difficulty\": 1-5, \"question_type\": \"选择题/填空题/解答题/计算题/实验题\", \"confidence\": 0-1}, ...]\n"
                "tag_ids 必须从可用标签中选择，每题最多选 3 个。只返回 JSON 数组，不要其他文字。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"可用标签：\n{tag_text}\n\n"
                f"题目列表：\n{all_q_text}\n\n"
                f"共 {len(questions)} 道题，请逐一分析并返回标注建议数组。"
            ),
        },
    ]

    response_text = await _call_llm(db, messages, temperature=0.3, timeout=120)

    # Parse JSON array response
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        suggestions_list = json.loads(text)
        if not isinstance(suggestions_list, list):
            suggestions_list = [suggestions_list]
    except json.JSONDecodeError:
        logger.warning(f"AI batch auto_tag response not JSON: {response_text[:300]}")
        return [{"id": q["id"], "tag_ids": [], "difficulty": None, "question_type": None, "confidence": 0} for q in questions]

    # Map results by ID
    results_map = {}
    valid_tag_ids = {t.id for t in tags}
    for s in suggestions_list:
        qid = s.get("id", "")
        suggested_ids = [tid for tid in s.get("tag_ids", []) if tid in valid_tag_ids][:3]
        results_map[qid] = {
            "id": qid,
            "tag_ids": suggested_ids,
            "difficulty": s.get("difficulty"),
            "question_type": s.get("question_type"),
            "confidence": s.get("confidence", 0.5),
        }

    # Ensure all questions have a result
    results = []
    for q in questions:
        if q["id"] in results_map:
            results.append(results_map[q["id"]])
        else:
            results.append({"id": q["id"], "tag_ids": [], "difficulty": None, "question_type": None, "confidence": 0})

    return results
