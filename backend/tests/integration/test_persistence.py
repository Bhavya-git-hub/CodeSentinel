"""Round-trip persistence against real PostgreSQL.

Marked ``requires_db``. These assert that the correctness constraints the model layer
declares actually hold once data goes through the database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Commit, File, FileMetric, Repository, Scan
from app.models.enums import ScanStatus

pytestmark = pytest.mark.requires_db


async def _repository(session: AsyncSession) -> Repository:
    repo = Repository(
        url=f"https://example.test/{uuid.uuid4()}", name="target", default_branch="main"
    )
    session.add(repo)
    await session.flush()
    return repo


async def test_scan_persists_the_reproducibility_record(db_session: AsyncSession) -> None:
    """Constraint C5: commit SHA, tool versions and config are stored together."""
    repo = await _repository(db_session)
    scan = Scan(
        repository_id=repo.id,
        commit_sha="a" * 40,
        status=ScanStatus.SUCCEEDED,
        tool_versions={"radon": "6.0.1", "pylint": "3.3.1"},
        analyzer_statuses={
            "coverage": {"status": "skipped", "error": "dependencies unavailable offline"}
        },
        config={"sandbox_timeout_seconds": 600},
    )
    db_session.add(scan)
    await db_session.flush()
    db_session.expunge_all()

    stored = (await db_session.execute(select(Scan).where(Scan.id == scan.id))).scalar_one()
    assert stored.commit_sha == "a" * 40
    assert stored.tool_versions["radon"] == "6.0.1"
    assert stored.analyzer_statuses["coverage"]["status"] == "skipped"
    assert stored.analyzer_statuses["coverage"]["error"]
    assert stored.config["sandbox_timeout_seconds"] == 600


async def test_enum_is_stored_as_its_value(db_session: AsyncSession) -> None:
    """The database holds the member value, matching what the API contract exposes."""
    repo = await _repository(db_session)
    scan = Scan(repository_id=repo.id, status=ScanStatus.PARTIAL)
    db_session.add(scan)
    await db_session.flush()

    raw = await db_session.execute(text("SELECT status FROM scans WHERE id = :id"), {"id": scan.id})
    assert raw.scalar_one() == "partial"


async def test_invalid_status_is_rejected_by_the_check_constraint(
    db_session: AsyncSession,
) -> None:
    """The CHECK is what stops any code path inventing a status."""
    repo = await _repository(db_session)
    statement = text(
        "INSERT INTO scans (id, repository_id, status, started_at, tool_versions, "
        "analyzer_statuses, config) "
        "VALUES (:id, :repo, 'not_a_status', now(), '{}', '{}', '{}')"
    )
    with pytest.raises(DBAPIError):
        await db_session.execute(statement, {"id": uuid.uuid4(), "repo": repo.id})


async def test_missing_metrics_persist_as_null_not_zero(db_session: AsyncSession) -> None:
    """Constraint C3: a file with no coverage data is not a file with 0% coverage."""
    repo = await _repository(db_session)
    scan = Scan(repository_id=repo.id, status=ScanStatus.PARTIAL)
    file = File(repository_id=repo.id, path="pkg/module.py", language="python", loc=42)
    db_session.add_all([scan, file])
    await db_session.flush()

    metric = FileMetric(scan_id=scan.id, file_id=file.id, cyclomatic_complexity=11.0)
    db_session.add(metric)
    await db_session.flush()
    db_session.expunge_all()

    stored = (
        await db_session.execute(select(FileMetric).where(FileMetric.id == metric.id))
    ).scalar_one()
    assert stored.cyclomatic_complexity == 11.0
    assert stored.coverage_pct is None, "unmeasured coverage must round-trip as NULL"
    assert stored.churn_score is None
    assert stored.risk_score is None


async def test_unlabelled_commit_round_trips_as_null(db_session: AsyncSession) -> None:
    """An unlabelled commit must not silently become a negative training example."""
    repo = await _repository(db_session)
    commit = Commit(
        repository_id=repo.id,
        sha="b" * 40,
        author_email="dev@example.test",
        authored_at=datetime.now(UTC),
        files_changed=3,
    )
    db_session.add(commit)
    await db_session.flush()
    db_session.expunge_all()

    stored = (await db_session.execute(select(Commit).where(Commit.id == commit.id))).scalar_one()
    assert stored.is_bugfix is None
    assert stored.is_defect_inducing is None
    assert stored.is_merge is False


async def test_repository_url_is_unique(db_session: AsyncSession) -> None:
    """Resubmitting the same URL must reuse the repository, not duplicate its history."""
    url = f"https://example.test/{uuid.uuid4()}"
    db_session.add(Repository(url=url, name="a"))
    await db_session.flush()
    db_session.add(Repository(url=url, name="b"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_deleting_a_scan_cascades_to_its_metrics(db_session: AsyncSession) -> None:
    repo = await _repository(db_session)
    scan = Scan(repository_id=repo.id, status=ScanStatus.SUCCEEDED)
    file = File(repository_id=repo.id, path="a.py")
    db_session.add_all([scan, file])
    await db_session.flush()
    db_session.add(FileMetric(scan_id=scan.id, file_id=file.id, risk_score=0.9))
    await db_session.flush()

    await db_session.execute(text("DELETE FROM scans WHERE id = :id"), {"id": scan.id})
    remaining = await db_session.execute(
        text("SELECT count(*) FROM file_metrics WHERE scan_id = :id"), {"id": scan.id}
    )
    assert remaining.scalar_one() == 0
