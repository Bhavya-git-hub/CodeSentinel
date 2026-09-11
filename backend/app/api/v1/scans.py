"""Submitting and inspecting scans.

The URL is validated here rather than in the worker so an unusable URL is refused
synchronously, with a reason. Making the caller poll a FAILED scan to discover they had a
typo is a worse API for no benefit.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, SettingsDep
from app.models.code import File
from app.models.enums import ScanStatus
from app.models.history import Commit
from app.models.repository import Repository, Scan
from app.schemas.scan import ScanAccepted, ScanDetail, ScanRequest
from app.services.ingestion.errors import UnsafeRepositoryUrlError
from app.services.ingestion.url import repository_name_from_url, validate_repository_url

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_scan(
    request: ScanRequest, session: SessionDep, settings: SettingsDep
) -> ScanAccepted:
    """Accept a repository for analysis and dispatch the ingestion task."""
    try:
        url = validate_repository_url(request.url, settings=settings)
    except UnsafeRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    repository = (
        await session.execute(select(Repository).where(Repository.url == url))
    ).scalar_one_or_none()
    if repository is None:
        repository = Repository(url=url, name=repository_name_from_url(url))
        session.add(repository)
        await session.flush()

    scan = Scan(
        repository_id=repository.id,
        status=ScanStatus.PENDING,
        # The configuration that produced this result, captured at dispatch (C5).
        config=settings.reproducibility_snapshot(),
    )
    session.add(scan)
    await session.commit()

    # Imported here so the API does not require a broker to be importable.
    from app.workers.tasks import run_scan

    run_scan.delay(str(scan.id))
    logger.info("scan.dispatched", scan_id=str(scan.id), url=url)
    return ScanAccepted(scan_id=scan.id, status=scan.status)


@router.get("/{scan_id}", response_model=ScanDetail)
async def get_scan(scan_id: uuid.UUID, session: SessionDep) -> ScanDetail:
    """Current state of one scan."""
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No scan with id {scan_id}")

    file_count = await _count_files(session, scan.repository_id)
    commit_count = await _count_commits(session, scan.repository_id)

    return ScanDetail(
        scan_id=scan.id,
        status=scan.status,
        commit_sha=scan.commit_sha,
        error=scan.error,
        file_count=file_count,
        commit_count=commit_count,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
    )


async def _count_files(session: AsyncSession, repository_id: uuid.UUID) -> int:
    """How many files were inventoried for this repository."""
    result = await session.execute(
        select(func.count()).select_from(File).where(File.repository_id == repository_id)
    )
    return int(result.scalar_one())


async def _count_commits(session: AsyncSession, repository_id: uuid.UUID) -> int:
    """How many commits were mined for this repository."""
    result = await session.execute(
        select(func.count()).select_from(Commit).where(Commit.repository_id == repository_id)
    )
    return int(result.scalar_one())
