"""SQLAlchemy async engine + session + Base."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields a DB session."""
    async with async_session_factory() as session:
        yield session


async def init_db():
    """Called at startup. Tables are managed by Alembic."""
    # We don't call create_all() here — Alembic handles migrations.
    # This function is kept for any future startup logic.
    pass
