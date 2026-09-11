"""The analysis pass: measure, score, persist.

Composes the sandboxed Radon adapter with host-side churn, and writes one FileMetric row
per inventoried file. This is the only module in phase 4 that touches both the sandbox and
the database; the pieces either side of it are independently testable without either.

It runs while the clone still exists. Phase 3 deletes the working tree when the scan
finishes, so analysis has to happen inside that window -- which is why the pipeline calls
this before its cleanup rather than as a later stage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.code import FileMetric, Finding
from app.models.enums import AnalyzerStatus
from app.models.history import Commit, FileChange
from app.services.analyzers import coverage as coverage_analyzer
from app.services.analyzers import findings as findings_analyzer
from app.services.analyzers import radon
from app.services.mining.churn import ChangeWeight, churn_score
from app.services.sandbox.errors import SandboxError
from app.services.sandbox.runner import Sandbox
from app.services.scoring.risk import RiskInputs, score_files

logger = structlog.get_logger(__name__)

ANALYZER_NAME = radon.ANALYZER_NAME


async def load_change_weights(
    session: AsyncSession, repository_id: uuid.UUID
) -> dict[str, list[ChangeWeight]]:
    """Per-path change history, for churn.

    Keyed on the path recorded *at that commit*, not on the file's id, because a file
    deleted or renamed before HEAD has no row in ``files`` -- and those are exactly the
    paths phase 3 went to the trouble of preserving (C4). Joining on file_id would
    silently discard them.
    """
    rows = (
        await session.execute(
            select(
                FileChange.path,
                FileChange.lines_added,
                FileChange.lines_deleted,
                Commit.authored_at,
            )
            .join(Commit, Commit.id == FileChange.commit_id)
            .where(Commit.repository_id == repository_id)
        )
    ).all()

    weights: dict[str, list[ChangeWeight]] = {}
    for path, added, deleted, authored_at in rows:
        weights.setdefault(path, []).append(
            ChangeWeight(changed_at=authored_at, lines_added=added, lines_deleted=deleted)
        )
    return weights


def build_inputs(
    paths: list[str],
    *,
    complexity: radon.MetricResult,
    weights: dict[str, list[ChangeWeight]],
    as_of: datetime,
    half_life_days: float,
) -> dict[str, RiskInputs]:
    """Assemble one RiskInputs per inventoried file.

    Every inventoried file gets an entry, including ones Radon could not measure. Omitting
    them would make an unparseable file vanish from the report entirely, which is worse
    than ranking it unknown: nobody looks for what is not listed.
    """
    return {
        path: RiskInputs(
            complexity=complexity.values.get(path),
            churn=churn_score(weights.get(path, []), as_of=as_of, half_life_days=half_life_days),
        )
        for path in paths
    }


async def run_analysis(
    session: AsyncSession,
    *,
    scan_id: uuid.UUID,
    repository_id: uuid.UUID,
    clone_path: Path,
    files_by_path: dict[str, uuid.UUID],
    as_of: datetime,
    settings: Settings,
) -> str | None:
    """Measure and score every inventoried file. Returns a reason if incomplete.

    A reason -- rather than an exception -- because an analyser that could not run is a
    recordable outcome, not a system fault: the churn half of the model still works, and
    a scan that reports which half it has is more useful than one that fails outright
    (C3).
    """
    if not settings.analysis_enabled:
        return "Analysis is disabled by configuration; no metrics were computed."

    if not files_by_path:
        return None

    complexity = radon.MetricResult()
    maintainability = radon.MetricResult()
    pylint_result = findings_analyzer.FindingsResult(findings_analyzer.PYLINT, [])
    bandit_result = findings_analyzer.FindingsResult(findings_analyzer.BANDIT, [])
    coverage_result = coverage_analyzer.CoverageResult(status=AnalyzerStatus.SKIPPED)
    analyzer_error: str | None = None

    try:
        with Sandbox(settings, source_dir=clone_path) as sandbox:
            complexity, maintainability = radon.measure(sandbox, settings)
            pylint_result = findings_analyzer.run_pylint(sandbox)
            bandit_result = findings_analyzer.run_bandit(sandbox)
            coverage_result = coverage_analyzer.run_coverage(sandbox)
    except SandboxError as exc:
        # Recorded, never swallowed: without this the scan would persist churn-only
        # metrics and look like a repository whose code is uniformly simple.
        analyzer_error = f"the sandbox was unavailable: {exc}"
        coverage_result = coverage_analyzer.CoverageResult(
            status=AnalyzerStatus.SKIPPED, error=analyzer_error
        )
        logger.warning("analysis.sandbox_unavailable", scan_id=str(scan_id), error=str(exc))

    if complexity.tool_error:
        analyzer_error = complexity.tool_error

    weights = await load_change_weights(session, repository_id)
    inputs = build_inputs(
        sorted(files_by_path),
        complexity=complexity,
        weights=weights,
        as_of=as_of,
        half_life_days=settings.churn_half_life_days,
    )
    scores = score_files(inputs)

    session.add_all(
        [
            FileMetric(
                scan_id=scan_id,
                file_id=files_by_path[path],
                cyclomatic_complexity=inputs[path].complexity,
                maintainability_index=maintainability.values.get(path),
                churn_score=inputs[path].churn,
                normalized_complexity=scores[path].normalized_complexity,
                normalized_churn=scores[path].normalized_churn,
                risk_score=scores[path].risk_score,
                # Absent from the coverage report means unmeasured, which stays None.
                # A file the suite never reached is not a file at 0% (anti-pattern #2).
                coverage_pct=coverage_result.percentages.get(path),
            )
            for path in inputs
        ]
    )
    await session.commit()

    await _persist_findings(
        session,
        scan_id=scan_id,
        files_by_path=files_by_path,
        results=[pylint_result, bandit_result],
    )

    unmeasured = sum(1 for score in scores.values() if score.risk_score is None)
    logger.info(
        "analysis.done",
        scan_id=str(scan_id),
        files=len(inputs),
        unmeasured=unmeasured,
        analyzer_error=analyzer_error,
    )

    reasons = [
        result.error for result in (pylint_result, bandit_result) if result.error is not None
    ]
    if coverage_result.status is not AnalyzerStatus.SUCCESS and coverage_result.error:
        reasons.append(f"coverage was skipped: {coverage_result.error}")

    if analyzer_error:
        reasons.insert(0, analyzer_error)
    if reasons:
        return " | ".join(reasons)
    if complexity.errors:
        # A per-file parse failure is not a tool failure, but it does mean the queue was
        # built from part of the repository, and the scan has to say which part.
        sample = ", ".join(sorted(complexity.errors)[:3])
        return (
            f"Radon could not measure {len(complexity.errors)} of {len(inputs)} files "
            f"(for example: {sample}). Those files are ranked as unknown, not as safe."
        )
    return None


async def _persist_findings(
    session: AsyncSession,
    *,
    scan_id: uuid.UUID,
    files_by_path: dict[str, uuid.UUID],
    results: list[findings_analyzer.FindingsResult],
) -> None:
    """Write findings, keeping the ones we cannot attribute to a file.

    ``file_id`` is nullable, so a finding about a path not in the inventory -- a file
    outside the walked tree, or one an analyser named differently -- is still recorded
    rather than dropped. Discarding it would quietly shrink the report, and the reader
    would have no way to know (C4).
    """
    rows = [
        Finding(
            scan_id=scan_id,
            file_id=files_by_path.get(record.path) if record.path else None,
            analyzer=record.analyzer,
            rule_id=record.rule_id,
            severity=record.severity,
            line_start=record.line_start,
            line_end=record.line_end,
            message=record.message,
        )
        for result in results
        for record in result.findings
    ]
    if not rows:
        return
    session.add_all(rows)
    await session.commit()
    logger.info("analysis.findings_persisted", scan_id=str(scan_id), count=len(rows))
