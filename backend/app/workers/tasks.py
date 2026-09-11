"""Celery tasks.

Celery tasks are synchronous and the data layer is asyncio throughout, so each task owns
an event loop for its own duration via ``asyncio.run``. The alternative -- a second,
synchronous driver for workers -- would mean every query could be written two ways and
the two kept in step forever. See ADR 0012.

The engine is built per task with NullPool because a pooled asyncpg connection created in
one loop and reused in another raises "attached to a different loop". tests/conftest.py
already carries this lesson for the same reason.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import build_engine
from app.services.ingestion.pipeline import run_ingestion
from app.services.retention import prune_scans
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="codesentinel.run_scan")
def run_scan(scan_id: str) -> None:
    """Ingest the repository for one scan.

    The id is parsed before any work starts: a malformed id is a programming error in the
    dispatcher, and failing immediately is better than a half-run scan.
    """
    parsed = uuid.UUID(scan_id)
    structlog.contextvars.bind_contextvars(scan_id=scan_id)
    try:
        asyncio.run(_run_scan(parsed))
    finally:
        structlog.contextvars.unbind_contextvars("scan_id")


async def _run_scan(scan_id: uuid.UUID) -> None:
    """The async body, with an engine scoped to this task's loop."""
    settings = get_settings()
    engine = build_engine(settings, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await run_ingestion(session, scan_id, settings=settings)
    finally:
        await engine.dispose()


@celery_app.task(name="codesentinel.prune_scans")
def prune_expired_scans() -> dict[str, int | str | None]:
    """Delete scans past the retention window, if one is configured.

    Returns a summary rather than None so the result backend holds something an operator
    can read after the fact. A pruning job that reports nothing leaves "did it run?" and
    "did it have nothing to do?" indistinguishable, which is the same collapse the rest
    of this system spends its design avoiding.
    """
    settings = get_settings()
    if settings.retention_days <= 0:
        # Not an error: this task is only scheduled when retention is on, so reaching
        # here means it was turned off after the schedule was built, or invoked by hand.
        logger.info("retention.disabled", retention_days=settings.retention_days)
        return {"scans_deleted": 0, "repositories_deleted": 0, "cutoff": None}

    return asyncio.run(_prune(settings.retention_days))


async def _prune(retention_days: int) -> dict[str, int | str | None]:
    """The async body, with an engine scoped to this task's loop (ADR 0012)."""
    settings = get_settings()
    engine = build_engine(settings, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await prune_scans(session, retention_days=retention_days)
            await session.commit()
    finally:
        await engine.dispose()

    return {
        "scans_deleted": result.scans_deleted,
        "repositories_deleted": result.repositories_deleted,
        "cutoff": result.cutoff.isoformat(),
    }
