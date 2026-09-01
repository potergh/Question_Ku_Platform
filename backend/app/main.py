"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.database import init_db
from app.routers import upload, questions, tags, settings as settings_router, basket, practices, recommend


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings.ensure_dirs()
    await init_db()

    # Clean up stale jobs (from previous server crash/restart)
    from app.database import async_session_factory
    from app.models import Job, Source
    from sqlalchemy import select
    from datetime import datetime

    async with async_session_factory() as db:
        # Mark running/queued jobs as failed
        result = await db.execute(
            select(Job).where(Job.status.in_(["running", "queued"]))
        )
        stale_jobs = result.scalars().all()
        for job in stale_jobs:
            job.status = "failed"
            job.error_message = "服务器重启，任务中断"
            job.finished_at = datetime.now()
            # Also mark corresponding source as error
            if job.source_id:
                source = await db.get(Source, job.source_id)
                if source and source.ocr_status == "pending":
                    source.ocr_status = "error"
        if stale_jobs:
            await db.commit()
            logging.info(f"Cleaned up {len(stale_jobs)} stale jobs")

    yield
    # Shutdown


app = FastAPI(
    title="智能题库讲义制作平台",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Formula-Degraded"],   # Word 导出公式降级清单（阶段 3）
)

# Routers
app.include_router(upload.router)
app.include_router(questions.router)
app.include_router(tags.router)
app.include_router(settings_router.router)
app.include_router(basket.router)
app.include_router(practices.router)
app.include_router(recommend.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# Serve frontend（生产静态模式）：SPA history 路由回退。
# 注册在所有 API 路由之后：已注册的 /api 路由优先命中；
# 未知前端子路径（如 /practice/editor 刷新）返回 index.html 由前端路由接管。
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    # 未注册的 /api/* 路径不得回退到前端，保持 404（避免误吞 API 路由）
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    dist = settings.base_dir / "frontend" / "dist"
    index = dist / "index.html"
    if not index.exists():
        raise HTTPException(404, "Frontend not built")
    if full_path:
        candidate = dist / full_path
        try:
            candidate = candidate.resolve()
            candidate.relative_to(dist.resolve())   # 路径穿越防护：只允许 dist 内文件
        except (ValueError, OSError):
            raise HTTPException(404, "Not Found")
        if candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(index)
