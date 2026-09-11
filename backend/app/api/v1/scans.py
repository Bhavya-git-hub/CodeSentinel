"""Submitting and inspecting scans.

The URL is validated here rather than in the worker so an unusable URL is refused
synchronously, with a reason. Making the caller poll a FAILED scan to discover they had a
typo is a worse API for no benefit.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import SessionDep, SettingsDep
from app.models.code import Dependency, File, FileMetric, Finding
from app.models.enums import ScanStatus, Severity
from app.models.history import Commit
from app.models.repository import Repository, Scan
from app.schemas.scan import (
    BlastRadius,
    FileRisk,
    FindingItem,
    FindingsPage,
    ImpactedFile,
    Limitation,
    RiskQueue,
    ScanAccepted,
    ScanDetail,
    ScanReport,
    ScanRequest,
)
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
                coverage_pct=metric.coverage_pct,
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


@router.get("/{scan_id}/findings", response_model=FindingsPage)
async def get_scan_findings(
    scan_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=1000),
) -> FindingsPage:
    """Every issue this scan recorded, worst first.

    Ordered by severity descending so the queue opens on what matters. The per-severity
    counts are computed over the whole scan rather than over the returned page, because a
    truncated page's counts would understate the problem it is reporting.
    """
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No scan with id {scan_id}")

    severity_order = case(
        {
            Severity.CRITICAL: 4,
            Severity.MAJOR: 3,
            Severity.MINOR: 2,
            Severity.INFO: 1,
        },
        value=Finding.severity,
        else_=0,
    )

    rows = (
        await session.execute(
            select(Finding, File.path)
            .outerjoin(File, File.id == Finding.file_id)
            .where(Finding.scan_id == scan_id)
            .order_by(severity_order.desc(), Finding.analyzer, Finding.rule_id)
            .limit(limit)
        )
    ).all()

    counts = (
        await session.execute(
            select(Finding.severity, func.count())
            .where(Finding.scan_id == scan_id)
            .group_by(Finding.severity)
        )
    ).all()
    by_severity = {str(severity.value): int(count) for severity, count in counts}

    return FindingsPage(
        scan_id=scan_id,
        status=scan.status,
        total=sum(by_severity.values()),
        by_severity=by_severity,
        analyzer_statuses=scan.analyzer_statuses,
        findings=[
            FindingItem(
                analyzer=finding.analyzer,
                rule_id=finding.rule_id,
                severity=finding.severity,
                message=finding.message,
                path=path,
                line_start=finding.line_start,
                line_end=finding.line_end,
            )
            for finding, path in rows
        ],
    )


@router.get("/{scan_id}/impact", response_model=BlastRadius)
async def get_blast_radius(
    scan_id: uuid.UUID,
    session: SessionDep,
    path: str = Query(min_length=1, max_length=1024),
    depth: int = Query(default=3, ge=1, le=10),
) -> BlastRadius:
    """Which files transitively import ``path``, and how far away each is.

    Traversal runs against the direction of the import, because the question is what
    breaks if this file changes. Depth is bounded: an unbounded answer on a large
    repository is every file, which tells a reviewer nothing.
    """
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No scan with id {scan_id}")

    source = aliased(File)
    target = aliased(File)
    rows = (
        await session.execute(
            select(source.path, target.path, Dependency.resolved)
            .select_from(Dependency)
            .join(source, source.id == Dependency.source_file_id)
            .outerjoin(target, target.id == Dependency.target_file_id)
            .where(Dependency.scan_id == scan_id)
        )
    ).all()

    importers: dict[str, list[str]] = {}
    resolved_edges = 0
    unresolved_edges = 0
    for source_path, target_path, resolved in rows:
        if resolved and target_path is not None:
            importers.setdefault(target_path, []).append(source_path)
            resolved_edges += 1
        else:
            unresolved_edges += 1

    distances: dict[str, int] = {}
    frontier = [path]
    for hop in range(1, depth + 1):
        nxt: list[str] = []
        for node in frontier:
            for importer in importers.get(node, []):
                if importer != path and importer not in distances:
                    distances[importer] = hop
                    nxt.append(importer)
        if not nxt:
            break
        frontier = nxt

    # .tuples() so the rows are plain tuples: dict() over Row objects is untyped, and
    # a comprehension that only unpacks them is redundant.
    risk_rows = (
        (
            await session.execute(
                select(File.path, FileMetric.risk_score)
                .join(FileMetric, FileMetric.file_id == File.id)
                .where(FileMetric.scan_id == scan_id)
            )
        )
        .tuples()
        .all()
    )
    risk_by_path: dict[str, float | None] = dict(risk_rows)

    impacted = sorted(
        (
            ImpactedFile(
                path=impacted_path,
                distance=distance,
                risk_score=risk_by_path.get(impacted_path),
            )
            for impacted_path, distance in distances.items()
        ),
        key=lambda item: (item.distance, item.path),
    )

    return BlastRadius(
        scan_id=scan_id,
        path=path,
        depth=depth,
        impacted=impacted,
        resolved_edges=resolved_edges,
        unresolved_edges=unresolved_edges,
    )


def _limitations(
    *,
    unmeasured: int,
    total_files: int,
    unresolved_edges: int,
    coverage_files: int,
    analyzer_statuses: dict[str, Any],
) -> list[Limitation]:
    """What this scan could not determine, phrased for a reader to act on.

    Assembled from the same numbers the report shows rather than from a separate record,
    so a limitation cannot drift out of step with the figure that produced it.
    """
    limits: list[Limitation] = []

    if unmeasured:
        limits.append(
            Limitation(
                subject="Unranked files",
                detail=f"{unmeasured} of {total_files} files have no risk score.",
                consequence=(
                    "They are unknown, not safe. They sort last in the queue, so a file "
                    "that could not be parsed will not appear near the top even if it is "
                    "the worst in the repository."
                ),
            )
        )

    if unresolved_edges:
        limits.append(
            Limitation(
                subject="Unresolved imports",
                detail=f"{unresolved_edges} import edges could not be resolved to a file.",
                consequence=(
                    "Third-party imports, dynamic imports and relative imports above the "
                    "repository root cannot be followed, so every blast radius here is a "
                    "floor rather than a ceiling."
                ),
            )
        )

    if coverage_files == 0:
        limits.append(
            Limitation(
                subject="Coverage",
                detail="No file has coverage data.",
                consequence=(
                    "The sandbox has no network, so a target whose tests need third-party "
                    "packages cannot run them. No file here is known to be untested; they "
                    "are unmeasured, which is a different thing."
                ),
            )
        )

    for analyzer, detail in analyzer_statuses.items():
        error = detail.get("error") if isinstance(detail, dict) else None
        if error:
            limits.append(
                Limitation(
                    subject=f"Analyser: {analyzer}",
                    detail=str(error),
                    consequence=(
                        "Whatever this analyser would have reported is absent, and its "
                        "absence is not evidence that there was nothing to report."
                    ),
                )
            )

    return limits


@router.get("/{scan_id}/report", response_model=ScanReport)
async def get_scan_report(
    scan_id: uuid.UUID,
    session: SessionDep,
    top: int = Query(default=20, ge=1, le=200),
) -> ScanReport:
    """One scan, assembled: the ranking, the findings, the graph, and its own limits.

    The limitations list is what makes this a report rather than a dump. A document that
    shows only what was found reads as complete, and a reader cannot then distinguish a
    clean repository from one nobody finished analysing (C3).
    """
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No scan with id {scan_id}")

    metric_rows = (
        await session.execute(
            select(FileMetric, File)
            .join(File, File.id == FileMetric.file_id)
            .where(FileMetric.scan_id == scan_id)
            .order_by(FileMetric.risk_score.desc().nullslast())
            .limit(top)
        )
    ).all()

    total_metrics = await _count_metrics(session, scan_id, unmeasured_only=False)
    unmeasured = await _count_metrics(session, scan_id, unmeasured_only=True)

    coverage_files = int(
        (
            await session.execute(
                select(func.count())
                .select_from(FileMetric)
                .where(FileMetric.scan_id == scan_id, FileMetric.coverage_pct.is_not(None))
            )
        ).scalar_one()
    )

    severity_rows = (
        await session.execute(
            select(Finding.severity, func.count())
            .where(Finding.scan_id == scan_id)
            .group_by(Finding.severity)
        )
    ).all()
    by_severity = {str(severity.value): int(count) for severity, count in severity_rows}

    edges = int(
        (
            await session.execute(
                select(func.count()).select_from(Dependency).where(Dependency.scan_id == scan_id)
            )
        ).scalar_one()
    )
    unresolved_edges = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Dependency)
                .where(Dependency.scan_id == scan_id, Dependency.resolved.is_(False))
            )
        ).scalar_one()
    )

    return ScanReport(
        scan_id=scan_id,
        status=scan.status,
        commit_sha=scan.commit_sha,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        file_count=await _count_files(session, scan.repository_id),
        commit_count=await _count_commits(session, scan.repository_id),
        files_ranked=total_metrics - unmeasured,
        files_unmeasured=unmeasured,
        findings_total=sum(by_severity.values()),
        findings_by_severity=by_severity,
        dependency_edges=edges,
        dependency_edges_unresolved=unresolved_edges,
        coverage_measured_files=coverage_files,
        top_risks=[
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
                coverage_pct=metric.coverage_pct,
            )
            for metric, file in metric_rows
        ],
        limitations=_limitations(
            unmeasured=unmeasured,
            total_files=total_metrics,
            unresolved_edges=unresolved_edges,
            coverage_files=coverage_files,
            analyzer_statuses=scan.analyzer_statuses,
        ),
        config=scan.config,
        analyzer_statuses=scan.analyzer_statuses,
    )
