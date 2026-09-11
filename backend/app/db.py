"""Async database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import Pool

from app.config import Settings, get_settings


def build_engine(settings: Settings, *, poolclass: type[Pool] | None = None) -> AsyncEngine:
    """Create an engine for the given settings.

    Takes settings explicitly rather than reading globals so tests and Alembic can build
    an engine against a different database without mutating process state.

    ``poolclass`` exists for the Celery worker, which runs each task under its own
    ``asyncio.run``. A pooled asyncpg connection created in one event loop and reused in
    another raises "attached to a different loop", so the worker passes ``NullPool``.
    """
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "pool_pre_ping": True}
    if poolclass is None:
        kwargs |= {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow}
    else:
        # pool_size and max_overflow are not valid arguments for NullPool, which is why
        # they live in this branch rather than being passed unconditionally.
        kwargs["poolclass"] = poolclass
    return create_async_engine(str(settings.database_url), **kwargs)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Process-wide engine, created lazily.

    Lazy creation matters: importing ``app.main`` must not require a reachable database,
    so the app can start and report itself unready rather than crashing on import.
    """
    return build_engine(get_settings())


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Process-wide session factory."""
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that rolls back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def reset_engine_cache() -> None:
    """Clear cached engine and sessionmaker. Used by tests after changing settings."""
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
