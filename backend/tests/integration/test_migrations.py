"""Migration correctness against a real PostgreSQL instance.

Marked ``requires_db``. When no PostgreSQL is reachable these skip with an explicit
reason rather than passing -- see tests/conftest.py.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.models import Base
from tests.conftest import TEST_DB_ENV_VAR, _run_migrations

pytestmark = pytest.mark.requires_db

EXPECTED_TABLES = {
    "repositories",
    "scans",
    "files",
    "file_metrics",
    "findings",
    "commits",
    "dependencies",
    "predictions",
}


def _table_names(sync_conn: Connection) -> set[str]:
    return set(inspect(sync_conn).get_table_names())


async def test_upgrade_head_creates_every_table(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(_table_names)
    assert tables >= EXPECTED_TABLES


async def test_migration_matches_the_models(db_engine: AsyncEngine) -> None:
    """The hand-written migration must produce exactly what the ORM declares.

    This is the check that keeps a hand-edited migration honest: after ``upgrade head``
    there must be no difference left for autogenerate to find. Without it, a model change
    that never made it into a migration would pass every other test in the suite.
    """

    def _diff(sync_conn: Connection) -> list[Any]:
        context = MigrationContext.configure(
            sync_conn, opts={"compare_type": True, "target_metadata": Base.metadata}
        )
        return compare_metadata(context, Base.metadata)

    async with db_engine.connect() as conn:
        diffs = await conn.run_sync(_diff)

    assert diffs == [], f"models and migration have diverged: {diffs}"


async def test_risk_queue_index_exists_with_descending_order(db_engine: AsyncEngine) -> None:
    """Verify the expression index survived into the real database.

    Autogenerate cannot render expression indexes, so this one was written by hand and is
    exactly the kind of thing that silently goes missing.
    """
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
            {"name": "ix_file_metrics_scan_id_risk_score"},
        )
        indexdef = result.scalar_one()
    assert "DESC NULLS LAST" in indexdef


async def test_enum_check_constraint_is_present(db_engine: AsyncEngine) -> None:
    """The CHECK must exist in the database, not merely be declared in the model."""
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": "ck_scans_scan_status"},
        )
        definition = result.scalar_one()
    assert "partial" in definition


async def test_downgrade_removes_every_table(db_engine: AsyncEngine) -> None:
    """A migration that cannot be reversed is a migration that cannot be recovered from.

    Depends on db_engine so it skips with the shared reason when no database is
    reachable, rather than failing on a missing environment variable.
    """
    url = os.environ[TEST_DB_ENV_VAR]
    await db_engine.dispose()
    await asyncio.to_thread(_run_migrations, url, "base")
    try:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            tables = await conn.run_sync(_table_names)
        await engine.dispose()
        assert not (EXPECTED_TABLES & tables)
    finally:
        await asyncio.to_thread(_run_migrations, url, "head")
