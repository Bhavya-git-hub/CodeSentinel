"""Shared test fixtures.

Tests that need PostgreSQL are marked ``requires_db`` and **skip with an explicit reason**
when no database is reachable. They are never silently passed, and SQLite is never
substituted: the schema uses JSONB, an expression index with ``NULLS LAST``, and asyncpg
semantics, so a SQLite run would prove nothing while looking green. That is the same rule
constraint C3 applies to analysis results, applied to our own suite.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from app.config import Settings, get_settings
from app.db import reset_engine_cache
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ENV_VAR = "CODESENTINEL_TEST_DATABASE_URL"


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    """Clear settings and engine caches around every test.

    Both are ``lru_cache``d for the process. Without this, a test that patches the
    environment would leak its configuration into every test that follows.
    """
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def settings() -> Settings:
    """Default settings, read from the environment."""
    return get_settings()


@pytest.fixture
def app(settings: Settings):  # type: ignore[no-untyped-def]
    """A fresh application instance per test."""
    return create_app(settings)


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    """HTTP client wired straight to the ASGI app -- no socket, no live server."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


def _test_database_url() -> str:
    """Return the test database URL or skip the test, saying exactly why."""
    url = os.environ.get(TEST_DB_ENV_VAR)
    if not url:
        pytest.skip(
            f"{TEST_DB_ENV_VAR} is not set, so no PostgreSQL instance is available. "
            "This test did not run; it was not verified.",
            allow_module_level=False,
        )
    return url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped engine against the test database, with the schema migrated.

    The schema is built by running the real Alembic migrations rather than
    ``metadata.create_all``, so the migration scripts themselves are exercised. A schema
    created from metadata could pass while the migration that has to produce it in
    production is broken.
    """
    url = _test_database_url()
    engine = create_async_engine(url, poolclass=None)

    try:
        async with engine.connect() as conn:
            await conn.rollback()
    except Exception as exc:  # noqa: BLE001 - the reason is reported in the skip message
        await engine.dispose()
        pytest.skip(f"PostgreSQL at {TEST_DB_ENV_VAR} is unreachable: {exc}")

    await asyncio.to_thread(_run_migrations, url, "head")
    try:
        yield engine
    finally:
        await engine.dispose()


def _run_migrations(url: str, revision: str) -> None:
    """Run Alembic in a worker thread.

    ``alembic/env.py`` calls ``asyncio.run`` for online migrations, which raises if a loop
    is already running. Running it on a thread with no loop of its own is what makes it
    callable from an async fixture.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={url}"]})()  # type: ignore[assignment]
    command.upgrade(cfg, revision)


@pytest_asyncio.fixture
async def db_connection(db_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back.

    Rolling back rather than recreating the schema keeps tests isolated without paying to
    drop and migrate between each one.
    """
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An ORM session bound to the rolled-back connection."""
    async with AsyncSession(bind=db_connection, expire_on_commit=False) as session:
        yield session
