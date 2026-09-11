"""The scans endpoints against a real database.

The broker is not required: dispatch is stubbed, because what these assert is the API
contract and what it persists, not that Celery works. Whether a worker picks the task up
is the worker's own test.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.enums import ScanStatus
from app.models.repository import Repository, Scan

pytestmark = pytest.mark.requires_db


@pytest.fixture(autouse=True)
def _dispatch_is_stubbed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture dispatched scan ids instead of reaching for a broker."""
    dispatched: list[str] = []

    class _Stub:
        @staticmethod
        def delay(scan_id: str) -> None:
            dispatched.append(scan_id)

    monkeypatch.setattr("app.workers.tasks.run_scan", _Stub)
    return dispatched


@pytest.fixture(autouse=True)
def _session_is_the_test_session(app: FastAPI, db_session: AsyncSession) -> None:
    """Route the API at the rolled-back test session so nothing survives the test."""

    async def _override() -> Any:
        yield db_session

    app.dependency_overrides[get_session] = _override


async def test_submitting_a_url_creates_a_pending_scan(
    client: AsyncClient, db_session: AsyncSession, _dispatch_is_stubbed: list[str]
) -> None:
    response = await client.post("/api/v1/scans", json={"url": "https://github.com/psf/requests"})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == ScanStatus.PENDING.value

    scan = (await db_session.execute(select(Scan))).scalars().one()
    assert str(scan.id) == body["scan_id"]
    assert _dispatch_is_stubbed == [body["scan_id"]], "the worker must actually be told"


async def test_the_dispatch_snapshot_is_recorded_on_the_scan(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """C5: the configuration a scan ran under is stored with it, at dispatch time."""
    await client.post("/api/v1/scans", json={"url": "https://github.com/psf/requests"})

    scan = (await db_session.execute(select(Scan))).scalars().one()
    assert scan.config["clone_allowed_protocols"] == ["https"]
    assert "max_repo_size_mb" in scan.config


async def test_the_same_repository_is_not_duplicated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two scans of one repository share its row, so history accumulates in one place."""
    url = "https://github.com/psf/requests"
    await client.post("/api/v1/scans", json={"url": url})
    await client.post("/api/v1/scans", json={"url": url})

    repositories = (await db_session.execute(select(Repository))).scalars().all()
    assert len(repositories) == 1
    scans = (await db_session.execute(select(Scan))).scalars().all()
    assert len(scans) == 2


async def test_an_unknown_scan_is_a_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/scans/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_a_scan_reports_its_counts(client: AsyncClient, db_session: AsyncSession) -> None:
    """The counts are zero here because nothing has run -- that is a real measurement.

    A scan that has not been ingested yet genuinely has no files, which is different from
    a scan whose inventory could not be determined. The latter is what scans.error and
    analyzer_statuses carry.
    """
    submitted = await client.post("/api/v1/scans", json={"url": "https://example.com/a/b"})
    scan_id = submitted.json()["scan_id"]

    response = await client.get(f"/api/v1/scans/{scan_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ScanStatus.PENDING.value
    assert body["commit_sha"] is None
    assert body["error"] is None
    assert body["file_count"] == 0
    assert body["commit_count"] == 0
    assert body["completed_at"] is None


async def test_the_list_is_newest_first(client: AsyncClient) -> None:
    """The history opens on what just happened, not on what happened first."""
    for path in ("a/one", "b/two", "c/three"):
        await client.post("/api/v1/scans", json={"url": f"https://example.com/{path}"})

    body = (await client.get("/api/v1/scans")).json()

    assert body["total"] == 3
    assert [row["repository_name"] for row in body["scans"]] == ["three", "two", "one"]


async def test_the_list_reports_the_total_not_the_page_length(client: AsyncClient) -> None:
    """A page length reported as the total makes a truncated history read as complete."""
    for index in range(5):
        await client.post("/api/v1/scans", json={"url": f"https://example.com/a/r{index}"})

    body = (await client.get("/api/v1/scans", params={"limit": 2})).json()

    assert len(body["scans"]) == 2
    assert body["total"] == 5, "the caller must be able to tell that there is more"


async def test_paging_returns_every_scan_exactly_once(client: AsyncClient) -> None:
    """The tiebreak on id is what makes this true when started_at collides.

    ``started_at`` is a server default, so scans created in quick succession can share a
    timestamp. Ordering on it alone lets a row appear on two consecutive pages while
    another never appears at all -- a paging bug that looks like data loss.
    """
    for index in range(6):
        await client.post("/api/v1/scans", json={"url": f"https://example.com/a/r{index}"})

    seen: list[str] = []
    for offset in (0, 2, 4):
        page = (await client.get("/api/v1/scans", params={"limit": 2, "offset": offset})).json()
        seen.extend(row["scan_id"] for row in page["scans"])

    assert len(seen) == 6
    assert len(set(seen)) == 6, "a scan was returned twice, so another was never returned"


async def test_filtering_by_status_narrows_the_total_too(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``total`` must describe the filtered set, or it contradicts the list beside it."""
    await client.post("/api/v1/scans", json={"url": "https://example.com/a/one"})
    await client.post("/api/v1/scans", json={"url": "https://example.com/a/two"})
    scan = (await db_session.execute(select(Scan))).scalars().first()
    assert scan is not None
    scan.status = ScanStatus.FAILED
    await db_session.flush()

    body = (await client.get("/api/v1/scans", params={"status": "failed"})).json()

    assert body["total"] == 1
    assert len(body["scans"]) == 1
    assert body["scans"][0]["status"] == ScanStatus.FAILED.value


async def test_an_unknown_status_is_refused_rather_than_ignored(client: AsyncClient) -> None:
    """Silently ignoring an unrecognised filter answers a question nobody asked."""
    response = await client.get("/api/v1/scans", params={"status": "nearly-done"})
    assert response.status_code == 422


async def test_the_list_names_the_repository_behind_each_scan(client: AsyncClient) -> None:
    """A scan id alone is unreadable; the list exists to be read."""
    await client.post("/api/v1/scans", json={"url": "https://github.com/psf/requests"})

    row = (await client.get("/api/v1/scans")).json()["scans"][0]

    assert row["repository_url"] == "https://github.com/psf/requests"
    assert row["repository_name"] == "requests"


async def test_an_empty_history_is_an_empty_list_not_an_error(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/scans")).json()
    assert body == {"total": 0, "limit": 20, "offset": 0, "scans": []}
