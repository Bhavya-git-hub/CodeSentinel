"""Pruning against a real PostgreSQL.

These need the real database because the thing being asserted is a foreign-key cascade.
``file_metrics`` and ``findings`` cascade from ``scans``; ``files`` and ``commits``
cascade from ``repositories``. Both are declared in DDL and enforced by the server, so a
test that stubbed the database would assert the ORM's intentions rather than the
behaviour, and the interesting failure -- rows surviving a delete that looked successful
-- is exactly the one a stub cannot produce.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code import File, FileMetric
from app.models.enums import ScanStatus
from app.models.history import Commit
from app.models.repository import Repository, Scan
from app.services.retention import prune_scans

pytestmark = pytest.mark.requires_db

NOW = datetime(2026, 6, 1, tzinfo=UTC)


async def _repository(session: AsyncSession, name: str) -> Repository:
    repository = Repository(url=f"https://example.com/a/{name}", name=name)
    session.add(repository)
    await session.flush()
    return repository


async def _scan(
    session: AsyncSession,
    repository: Repository,
    *,
    age_days: float,
    status: ScanStatus = ScanStatus.SUCCEEDED,
) -> Scan:
    scan = Scan(
        repository_id=repository.id,
        status=status,
        started_at=NOW - timedelta(days=age_days),
        commit_sha="a" * 40,
    )
    session.add(scan)
    await session.flush()
    return scan


async def _count(session: AsyncSession, model: type) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_a_scan_older_than_the_window_is_deleted(db_session: AsyncSession) -> None:
    repository = await _repository(db_session, "old")
    await _scan(db_session, repository, age_days=40)

    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.scans_deleted == 1
    assert await _count(db_session, Scan) == 0


async def test_a_scan_inside_the_window_is_kept(db_session: AsyncSession) -> None:
    repository = await _repository(db_session, "recent")
    await _scan(db_session, repository, age_days=10)

    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.scans_deleted == 0
    assert await _count(db_session, Scan) == 1


async def test_a_running_scan_is_never_pruned_however_old(db_session: AsyncSession) -> None:
    """An old RUNNING scan is stuck, not expired.

    Deleting it would pull the row out from under a worker that is still writing to it,
    turning a stuck scan into a foreign-key error mid-pipeline -- and would hide the fact
    that scans are getting stuck at all, which is the thing someone needs to see.
    """
    repository = await _repository(db_session, "stuck")
    await _scan(db_session, repository, age_days=400, status=ScanStatus.RUNNING)

    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.scans_deleted == 0
    assert await _count(db_session, Scan) == 1


async def test_a_pending_scan_is_never_pruned_either(db_session: AsyncSession) -> None:
    repository = await _repository(db_session, "queued")
    await _scan(db_session, repository, age_days=400, status=ScanStatus.PENDING)

    assert (await prune_scans(db_session, retention_days=30, now=NOW)).scans_deleted == 0


async def test_a_failed_scan_expires_like_any_other(db_session: AsyncSession) -> None:
    """FAILED is terminal. Keeping failures forever would bound nothing."""
    repository = await _repository(db_session, "failed")
    await _scan(db_session, repository, age_days=40, status=ScanStatus.FAILED)

    assert (await prune_scans(db_session, retention_days=30, now=NOW)).scans_deleted == 1


async def test_the_scans_own_rows_go_with_it(db_session: AsyncSession) -> None:
    """file_metrics cascades from scans. If it did not, pruning would orphan rows."""
    repository = await _repository(db_session, "metrics")
    scan = await _scan(db_session, repository, age_days=40)
    file = File(repository_id=repository.id, path="pkg/mod.py", is_test=False, loc=10)
    db_session.add(file)
    await db_session.flush()
    db_session.add(FileMetric(scan_id=scan.id, file_id=file.id, risk_score=0.5))
    await db_session.flush()

    await prune_scans(db_session, retention_days=30, now=NOW)

    assert await _count(db_session, FileMetric) == 0


async def test_a_repository_with_no_scans_left_is_removed_too(db_session: AsyncSession) -> None:
    """This is what actually reclaims the space.

    commits and files cascade from repositories, not from scans. A pruner that deleted
    only scans would report a large number of rows removed and leave the database
    growing exactly as fast as before -- one scan of psf/requests writes 4,881 commits.
    """
    repository = await _repository(db_session, "gone")
    await _scan(db_session, repository, age_days=40)
    db_session.add(
        Commit(
            repository_id=repository.id,
            sha="b" * 40,
            author_email="a@example.com",
            authored_at=NOW - timedelta(days=50),
            message_summary="whatever",
        )
    )
    db_session.add(File(repository_id=repository.id, path="pkg/mod.py", is_test=False, loc=10))
    await db_session.flush()

    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.repositories_deleted == 1
    assert await _count(db_session, Commit) == 0
    assert await _count(db_session, File) == 0


async def test_a_repository_keeping_one_scan_keeps_its_history(db_session: AsyncSession) -> None:
    """The dangerous inverse of the test above: pruning must not take a live repository."""
    repository = await _repository(db_session, "mixed")
    await _scan(db_session, repository, age_days=40)
    await _scan(db_session, repository, age_days=1)
    db_session.add(File(repository_id=repository.id, path="pkg/mod.py", is_test=False, loc=10))
    await db_session.flush()

    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.scans_deleted == 1
    assert result.repositories_deleted == 0
    assert await _count(db_session, File) == 1, "the surviving scan's files were deleted"


async def test_one_repository_expiring_does_not_take_another(db_session: AsyncSession) -> None:
    expired = await _repository(db_session, "expired")
    live = await _repository(db_session, "live")
    await _scan(db_session, expired, age_days=40)
    await _scan(db_session, live, age_days=1)

    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.repositories_deleted == 1
    survivors = (await db_session.execute(select(Repository.name))).scalars().all()
    assert survivors == ["live"]


async def test_pruning_an_empty_database_is_a_no_op(db_session: AsyncSession) -> None:
    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.scans_deleted == 0
    assert result.repositories_deleted == 0


async def test_the_cutoff_is_reported_so_a_run_can_be_audited(db_session: AsyncSession) -> None:
    """ "Deleted 4,000 scans" is only checkable if the boundary it used is stated."""
    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.cutoff == NOW - timedelta(days=30)


async def test_a_repository_that_never_had_a_scan_is_removed(db_session: AsyncSession) -> None:
    """Safe because a repository and its first scan are written in one transaction.

    ``submit_scan`` adds the repository, flushes to get its id, adds the scan, and
    commits once. So a *committed* repository with no scans is never an in-flight
    submission -- it is a leftover, and leaving it would mean the orphan sweep missed
    the only rows it exists to collect.
    """
    db_session.add(Repository(url="https://example.com/a/bare", name="bare"))
    await db_session.flush()

    result = await prune_scans(db_session, retention_days=30, now=NOW)

    assert result.repositories_deleted == 1
    assert await _count(db_session, Repository) == 0
