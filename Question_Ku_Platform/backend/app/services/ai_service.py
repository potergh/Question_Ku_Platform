"""AI service — reads config from DB, calls OpenAI-compatible API."""

import json
import logging
import re
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
    """读取文本模型配置。凭据（Key 或 Base URL 任一）缺失时抛错。

    与 ``vlm_client.get_vision_config`` 同一套判据：**不再看 ai_mode**，只看
    有没有可用来发请求的凭据。那三档识别模式已由导入页的通道选择代替，设置页
    再留一个总开关会和导入页打架。

    为什么"Key 或 Base URL 任一"即可：本地 Ollama 一类端点不需要 Key，
    若硬性要求 Key 会把这类自建端点挡在外面；反过来只填 Key 不填端点也走不通，
    所以两个都空才算没配。
    """
    result = await db.execute(select(Settings).where(Settings.id == 1))
    s = result.scalar_one_or_none()
    if not s:
        raise AIServiceError("AI 未配置，请先在设置页面配置")

    base_url = (s.ai_base_url or "").rstrip("/")
    if s.ai_mode == "local":
        # 历史库里可能还存着 local：保留这一档的端点覆写，不静默改掉已有配置。
        base_url = "http://localhost:11434/v1"

    if not (s.ai_api_key or "").strip() and not base_url:
        raise AIServiceError("未配置 API Key 或 Base URL，请在设置页面填写")
    # 模型名默认已留空（不再预设 gpt-4o）：空模型名发出去只会换来厂商的
    # "model not found"，而用户看到的是自己的 Key 明明填对了 —— 必须在这里拦。
    if not (s.ai_model or "").strip():
        raise AIServiceError("未配置模型名，请在设置页面的「模型」一栏填写")

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


SOLVE_SYSTEM = """你是中学理科老师。根据给出的题目，给出**答案**与**解析**。

输出 JSON（严格遵守）：
{
  "answer": "答案本体",
  "explanation": "解析文字，公式用 LaTeX 行内 $...$"
}

规则：
1. 只依据题目给出的条件作答，不要臆造题目里没有的数据。
2. answer 保持简洁：选择题只给选项字母；计算题给结论，多个小问按 (1)(2) 分段。
3. explanation 写清关键步骤与依据（公式、定律、判断理由），不要只给结果。
4. 题目信息不足或存在歧义时，不要猜，在 explanation 里说明缺什么。
5. 只输出 JSON。"""


def _parse_json_block(text: str) -> dict | None:
    """从模型回复里取出 JSON 对象。

    模型经常把 JSON 包在 ```json 围栏里，或前后加一句说明；两种都要能吃下。
    """
    if not text:
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def solve_question(
    db: AsyncSession,
    *,
    content: str,
    options: list | None = None,
    subject: str | None = None,
    answer: str | None = None,
) -> dict:
    """让模型给出一道题的答案与解析。

    **不落库**：结果交用户核对后再保存。AI 解析会出错，直接写进题库比缺答案更糟。
    """
    parts: list[str] = []
    if subject:
        parts.append(f"学科：{subject}")
    parts.append(f"题目：{content or ''}")
    if options:
        rendered = "\n".join(
            f"{opt.get('label', '')}. {opt.get('content', '')}"
            for opt in options
            if isinstance(opt, dict)
        )
        if rendered:
            parts.append(f"选项：\n{rendered}")
    if answer:
        parts.append(f"题库里已有的答案是「{answer}」，如与你的判断不一致，请在解析里说明。")

    reply = await _call_llm(
        db,
        [
            {"role": "system", "content": SOLVE_SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        timeout=120,
    )

    data = _parse_json_block(reply) or {}
    solved_answer = str(data.get("answer") or "").strip() or None
    explanation = str(data.get("explanation") or "").strip() or None
    if solved_answer is None and explanation is None:
        # 模型没按 JSON 回：把整段当解析，至少不丢内容（宁可让用户看到原文）
        explanation = reply.strip() or None
    return {"answer": solved_answer, "explanation": explanation}


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
