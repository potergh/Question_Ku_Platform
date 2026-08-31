"""Settings router — GET/PUT settings, test AI connection."""

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import Settings
from app.schemas.setting import (
    SettingsResponse, SettingsUpdate,
    TestConnectionRequest, TestConnectionResponse,
)

router = APIRouter()


async def _get_or_create_settings(db: AsyncSession) -> Settings:
    """Get the singleton settings row, creating if needed."""
    result = await db.execute(select(Settings).where(Settings.id == 1))
    s = result.scalar_one_or_none()
    if not s:
        s = Settings(id=1)
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return s


@router.get("/api/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get current settings with masked API key."""
    s = await _get_or_create_settings(db)
    return SettingsResponse(
        ai_mode=s.ai_mode,
        ai_api_key_masked=Settings.mask_key(s.ai_api_key),
        ai_base_url=s.ai_base_url,
        ai_model=s.ai_model,
        ai_temperature=s.ai_temperature,
        ai_review_prompt=s.ai_review_prompt,
    )


@router.put("/api/settings", response_model=SettingsResponse)
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Update settings. If ai_api_key is empty/omitted, existing key is preserved."""
    s = await _get_or_create_settings(db)

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "ai_api_key":
            # Only update key if a non-empty value is provided
            if value:
                s.ai_api_key = value
            # If empty string or None sent, skip — keep existing key
        else:
            setattr(s, field, value)

    await db.commit()
    await db.refresh(s)

    return SettingsResponse(
        ai_mode=s.ai_mode,
        ai_api_key_masked=Settings.mask_key(s.ai_api_key),
        ai_base_url=s.ai_base_url,
        ai_model=s.ai_model,
        ai_temperature=s.ai_temperature,
        ai_review_prompt=s.ai_review_prompt,
    )


@router.post("/api/settings/test", response_model=TestConnectionResponse)
async def test_connection(data: TestConnectionRequest, db: AsyncSession = Depends(get_db)):
    """Test AI API connection by making a minimal request."""
    import httpx

    # 前端在 Key 输入框留空时会传占位值（'test'）：回退用已保存的 Key 测试
    api_key = data.api_key
    if not api_key or api_key == "test":
        s = await _get_or_create_settings(db)
        api_key = s.ai_api_key or ""
    if not api_key:
        return TestConnectionResponse(ok=False, message="未配置 API Key，请先填写并保存")

    start = time.time()
    try:
        # Build the request to the chat completions endpoint
        url = data.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": data.model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)

        latency = int((time.time() - start) * 1000)

        if resp.status_code == 200:
            return TestConnectionResponse(ok=True, message="连接成功", latency_ms=latency)
        else:
            body = resp.text[:200]
            return TestConnectionResponse(
                ok=False, message=f"API 返回错误 (HTTP {resp.status_code}): {body}", latency_ms=latency
            )
    except httpx.TimeoutException:
        return TestConnectionResponse(ok=False, message="连接超时，请检查 Base URL")
    except httpx.ConnectError:
        return TestConnectionResponse(ok=False, message="无法连接到服务器，请检查 Base URL")
    except Exception as e:
        return TestConnectionResponse(ok=False, message=f"连接失败: {str(e)[:200]}")
