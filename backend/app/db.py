"""Async database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def build_engine(settings: Settings) -> AsyncEngine:
    """Create an engine for the given settings.

    Takes settings explicitly rather than reading globals so tests and Alembic can build
    an engine against a different database without mutating process state.
    """
    return create_async_engine(
        str(settings.database_url),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


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
