"""Deleting scans that are older than the configured retention window.

The deployment guide listed "scan rows and their findings accumulate without bound;
there is no pruning job" as a thing this system did not do. This is that job.

Three decisions in here are not obvious from the code:

**Deleting scans is not enough to bound growth.** ``file_metrics``, ``findings``,
``dependencies`` and ``predictions`` cascade from ``scans``, but ``files``, ``commits``
and ``file_changes`` cascade from ``repositories`` -- and those are the bulk. One scan of
psf/requests writes 4,881 commit rows and a file-change row for every path each of them
touched. A pruner that deleted only scans would delete the small tables, report a large
number of rows removed, and leave the database growing exactly as fast as before. So a
repository with no scans left is deleted too, which is what actually reclaims the space.

**A retention window of zero is not "delete everything".** ``retention_days=0`` means
retention is disabled, and passing it here raises rather than computing a cutoff of
``now``. The arithmetic for "0 days" is a cutoff that deletes the entire history, and a
misread setting is the likeliest way anyone ever calls this function wrongly.

**Only terminal scans are pruned.** A PENDING or RUNNING scan older than the cutoff is a
stuck scan, not an expired one, and deleting it out from under a worker that is still
writing to it turns a stuck scan into a foreign-key error in the middle of a pipeline.
Stuck scans need their own answer; this is not it, and silently eating them would hide
the fact that they exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, Result, delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ScanStatus
from app.models.repository import Repository, Scan

logger = structlog.get_logger(__name__)

#: Statuses a scan can be pruned from. Anything else is still in flight.
TERMINAL_STATUSES = (ScanStatus.SUCCEEDED, ScanStatus.PARTIAL, ScanStatus.FAILED)


class RetentionDisabledError(ValueError):
    """Raised when the pruner is asked to run with retention switched off.

    Deliberately an error rather than a no-op return. ``retention_days=0`` reaching the
    cutoff arithmetic produces ``now``, which selects every scan ever recorded; refusing
    loudly is the difference between a configuration mistake and a wiped history.
    """


def _rowcount(result: Result[Any]) -> int:
    """How many rows a DELETE removed.

    ``AsyncSession.execute`` is declared as returning ``Result``, which carries no
    ``rowcount`` -- that lives on ``CursorResult``, which is what a DML statement
    actually returns. The cast states that rather than reaching through ``getattr``,
    which would hide a genuine type change behind a silent default.
    """
    return int(cast("CursorResult[Any]", result).rowcount)


@dataclass(frozen=True)
class PruneResult:
    """What one pruning pass removed.

    ``repositories_deleted`` is reported separately rather than folded into a single
    total, because the two numbers answer different questions: one is how much history
    expired, the other is how much storage that actually reclaimed.
    """

    cutoff: datetime
    scans_deleted: int
    repositories_deleted: int


async def prune_scans(
    session: AsyncSession,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> PruneResult:
    """Delete terminal scans started before the cutoff, and any repository left empty.

    ``now`` is injectable so a test can state the passage of time instead of sleeping
    through it. It is not a setting: two pruning passes disagreeing about what "now" is
    would delete different sets from the same data.
    """
    if retention_days <= 0:
        raise RetentionDisabledError(
            f"prune_scans called with retention_days={retention_days}. Zero means "
            "retention is disabled, not that everything has expired -- the caller is "
            "expected to check before calling."
        )

    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(days=retention_days)

    doomed = select(Scan.id).where(
        Scan.started_at < cutoff,
        Scan.status.in_(TERMINAL_STATUSES),
    )
    scans_deleted = _rowcount(
        await session.execute(
            delete(Scan).where(Scan.id.in_(doomed)).execution_options(synchronize_session=False)
        )
    )

    # Repositories whose last scan just went. Evaluated after the delete above, so the
    # correlated EXISTS sees the post-delete state within this transaction.
    orphaned = select(Repository.id).where(
        ~exists(select(Scan.id).where(Scan.repository_id == Repository.id))
    )
    repositories_deleted = _rowcount(
        await session.execute(
            delete(Repository)
            .where(Repository.id.in_(orphaned))
            .execution_options(synchronize_session=False)
        )
    )

    result = PruneResult(
        cutoff=cutoff,
        scans_deleted=scans_deleted,
        repositories_deleted=repositories_deleted,
    )
    logger.info(
        "retention.pruned",
        cutoff=cutoff.isoformat(),
        retention_days=retention_days,
        scans_deleted=result.scans_deleted,
        repositories_deleted=result.repositories_deleted,
    )
    return result
