"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import upload, questions, handouts, tags, settings as settings_router


logging.basicConfig(level=logging.INFO)

# Frontend dist directory (for production serving)
FRONTEND_DIST = settings.base_dir / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings.ensure_dirs()
    await init_db()
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
)

# Routers
app.include_router(upload.router)
app.include_router(questions.router)
app.include_router(handouts.router)
app.include_router(tags.router)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


# Serve frontend static files (production mode)
# This must be AFTER all API routes
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
