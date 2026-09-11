"""The risk queue endpoint against a real database.

Ordering with NULLs is the thing worth asserting through PostgreSQL: the index is
``DESC NULLS LAST``, and a query that forgot the NULLS LAST would put every unmeasured
file at the top of the review queue.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.code import File, FileMetric
from app.models.enums import ScanStatus
from app.models.repository import Repository, Scan

pytestmark = pytest.mark.requires_db


@pytest.fixture(autouse=True)
def _session_is_the_test_session(app: FastAPI, db_session: AsyncSession) -> None:
    async def _override() -> Any:
        yield db_session

    app.dependency_overrides[get_session] = _override


async def _scan_with_metrics(session: AsyncSession) -> Scan:
    """A scan over three files: high risk, low risk, and one that could not be measured."""
    repository = Repository(url="https://example.test/risk", name="risk/fixture")
    session.add(repository)
    await session.flush()

    scan = Scan(repository_id=repository.id, status=ScanStatus.SUCCEEDED)
    session.add(scan)
    await session.flush()

    specs = [
        ("hot.py", 0.9, 40.0, 500.0),
        ("cold.py", 0.1, 5.0, 2.0),
        ("broken.py", None, None, 300.0),
    ]
    for path, risk, complexity, churn in specs:
        file = File(repository_id=repository.id, path=path)
        session.add(file)
        await session.flush()
        session.add(
            FileMetric(
                scan_id=scan.id,
                file_id=file.id,
                cyclomatic_complexity=complexity,
                churn_score=churn,
                risk_score=risk,
            )
        )
    await session.flush()
    return scan


async def test_files_are_ranked_by_risk_descending(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    scan = await _scan_with_metrics(db_session)

    response = await client.get(f"/api/v1/scans/{scan.id}/metrics")

    assert response.status_code == 200
    paths = [item["path"] for item in response.json()["files"]]
    assert paths[0] == "hot.py"
    assert paths[1] == "cold.py"


async def test_an_unmeasured_file_sorts_last_rather_than_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """NULL is unknown, not infinite. Without NULLS LAST it would head the queue."""
    scan = await _scan_with_metrics(db_session)

    body = (await client.get(f"/api/v1/scans/{scan.id}/metrics")).json()

    assert body["files"][-1]["path"] == "broken.py"
    assert body["files"][-1]["risk_score"] is None


async def test_the_queue_reports_how_much_it_could_not_measure(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A short queue must not read as a clean bill of health (C3)."""
    scan = await _scan_with_metrics(db_session)

    body = (await client.get(f"/api/v1/scans/{scan.id}/metrics")).json()

    assert body["total_files"] == 3
    assert body["unmeasured"] == 1


async def test_metrics_for_an_unknown_scan_are_a_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/scans/00000000-0000-0000-0000-000000000000/metrics")
    assert response.status_code == 404


async def test_findings_are_returned_worst_first_with_whole_scan_counts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Severity ordering and counts over the whole scan, not the returned page.

    A truncated page whose counts described only itself would understate the problem it
    is reporting.
    """
    from app.models.code import Finding
    from app.models.enums import Severity

    scan = await _scan_with_metrics(db_session)
    for severity, rule in [
        (Severity.INFO, "C0114"),
        (Severity.CRITICAL, "B602"),
        (Severity.MINOR, "W0612"),
    ]:
        db_session.add(
            Finding(
                scan_id=scan.id,
                file_id=None,
                analyzer="pylint",
                rule_id=rule,
                severity=severity,
                message=f"{rule} message",
            )
        )
    await db_session.flush()

    body = (await client.get(f"/api/v1/scans/{scan.id}/findings")).json()

    assert [f["rule_id"] for f in body["findings"]] == ["B602", "W0612", "C0114"]
    assert body["total"] == 3
    assert body["by_severity"]["critical"] == 1


async def test_a_finding_with_no_file_is_still_returned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """file_id is nullable so an unattributable finding is recorded, not dropped (C4)."""
    from app.models.code import Finding
    from app.models.enums import Severity

    scan = await _scan_with_metrics(db_session)
    db_session.add(
        Finding(
            scan_id=scan.id,
            file_id=None,
            analyzer="bandit",
            rule_id="B101",
            severity=Severity.MAJOR,
            message="project-level finding",
        )
    )
    await db_session.flush()

    body = (await client.get(f"/api/v1/scans/{scan.id}/findings")).json()

    assert body["findings"][0]["path"] is None
    assert body["total"] == 1


async def _scan_with_an_inventory_but_no_metrics(session: AsyncSession) -> Scan:
    """What a scan looks like when analysis never ran: files inventoried, no metric rows.

    No other fixture produces this shape, because every fixture that inventories also
    analyses. It is the shape a real deployment has whenever there is no Docker daemon or
    ``analysis_enabled`` is false -- which is how the defect below reached a live scan
    without any test noticing.
    """
    repository = Repository(url="https://example.test/unanalysed", name="a/unanalysed")
    session.add(repository)
    await session.flush()

    scan = Scan(repository_id=repository.id, status=ScanStatus.PARTIAL)
    session.add(scan)
    await session.flush()

    for path in ("a.py", "b.py", "c.py", "notes.md"):
        session.add(File(repository_id=repository.id, path=path))
    await session.flush()
    return scan


async def test_a_scan_that_measured_nothing_reports_its_files_as_unmeasured(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Not as an empty repository, which is what it used to say.

    ``total_files`` counted FileMetric rows. With analysis skipped there are none, so a
    repository with four files reported "0 files, 0 unmeasured" -- indistinguishable from
    a repository containing nothing at all, and the opposite of what happened.
    """
    scan = await _scan_with_an_inventory_but_no_metrics(db_session)

    body = (await client.get(f"/api/v1/scans/{scan.id}/metrics")).json()

    assert body["total_files"] == 4, "the inventory is the denominator, not the metric rows"
    assert body["unmeasured"] == 4, "every file went unmeasured; none of them is absent"


async def test_the_report_admits_that_nothing_was_ranked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The caveat is raised by a non-zero ``unmeasured``, so zeroing it silenced it.

    The scan that measured least was therefore the one that admitted to least, which is
    the precise inversion this codebase exists to prevent.
    """
    scan = await _scan_with_an_inventory_but_no_metrics(db_session)

    report = (await client.get(f"/api/v1/scans/{scan.id}/report")).json()

    assert report["files_ranked"] == 0
    assert report["files_unmeasured"] == 4
    subjects = [limitation["subject"] for limitation in report["limitations"]]
    assert "Unranked files" in subjects, f"no caveat was raised; got {subjects}"


async def test_ranked_and_unmeasured_always_account_for_every_file(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A reader adds these two numbers and expects the file count. It has to hold."""
    scan = await _scan_with_metrics(db_session)

    report = (await client.get(f"/api/v1/scans/{scan.id}/report")).json()

    assert report["files_ranked"] + report["files_unmeasured"] == report["file_count"]
