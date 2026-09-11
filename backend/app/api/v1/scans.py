"""Submitting and inspecting scans.

The URL is validated here rather than in the worker so an unusable URL is refused
synchronously, with a reason. Making the caller poll a FAILED scan to discover they had a
typo is a worse API for no benefit.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, SettingsDep
from app.models.code import File, FileMetric
from app.models.enums import ScanStatus
from app.models.history import Commit
from app.models.repository import Repository, Scan
from app.schemas.scan import FileRisk, RiskQueue, ScanAccepted, ScanDetail, ScanRequest
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


@router.get("/{scan_id}/metrics", response_model=RiskQueue)
async def get_scan_metrics(
    scan_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=500),
) -> RiskQueue:
    """The risk-ranked review queue for one scan.

    Ordered by risk descending with NULLs last, matching
    ``ix_file_metrics_scan_id_risk_score``. A file whose complexity could not be measured
    has a NULL score and sorts to the end -- it is unknown, not safe, and the
    ``unmeasured`` count says how many such files the queue is hiding at the bottom.
    """
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No scan with id {scan_id}")

    rows = (
        await session.execute(
            select(FileMetric, File)
            .join(File, File.id == FileMetric.file_id)
            .where(FileMetric.scan_id == scan_id)
            .order_by(FileMetric.risk_score.desc().nullslast())
            .limit(limit)
        )
    ).all()

    total_files = await _count_metrics(session, scan_id, unmeasured_only=False)
    unmeasured = await _count_metrics(session, scan_id, unmeasured_only=True)

    return RiskQueue(
        scan_id=scan_id,
        status=scan.status,
        total_files=total_files,
        unmeasured=unmeasured,
        analyzer_statuses=scan.analyzer_statuses,
        files=[
            FileRisk(
                path=file.path,
                is_test=file.is_test,
                loc=file.loc,
                cyclomatic_complexity=metric.cyclomatic_complexity,
                maintainability_index=metric.maintainability_index,
                churn_score=metric.churn_score,
                normalized_complexity=metric.normalized_complexity,
                normalized_churn=metric.normalized_churn,
                risk_score=metric.risk_score,
            )
            for metric, file in rows
        ],
    )


async def _count_metrics(
    session: AsyncSession, scan_id: uuid.UUID, *, unmeasured_only: bool
) -> int:
    """Count this scan's metric rows, optionally only the ones with no risk score."""
    query = select(func.count()).select_from(FileMetric).where(FileMetric.scan_id == scan_id)
    if unmeasured_only:
        query = query.where(FileMetric.risk_score.is_(None))
    result = await session.execute(query)
    return int(result.scalar_one())
