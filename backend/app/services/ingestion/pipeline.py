"""Orchestration: a scan from PENDING to a terminal status.

The services below this module perform no database I/O; this one owns the session and the
scan's lifecycle. Keeping it that way is what lets the cloner and the miner be tested
without a database.

The clone is removed in a ``finally``. A scan that fails is exactly the case where a
multi-gigabyte working tree would otherwise be left behind, and the host fills up from
the failures rather than the successes.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.code import File
from app.models.enums import ScanStatus
from app.models.history import Commit, FileChange
from app.models.repository import Repository, Scan
from app.services.analyzers.analysis import ANALYZER_NAME, run_analysis
from app.services.ingestion.cloner import clone_repository, remove_tree
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.history import mine_history
from app.services.ingestion.inventory import inventory_files

logger = structlog.get_logger(__name__)

COMMIT_BATCH_SIZE = 500


def classify_outcome(*, history_error: str | None, analysis_error: str | None = None) -> ScanStatus:
    """The terminal status for a run whose clone and inventory both succeeded.

    PARTIAL rather than FAILED when history is incomplete: the file inventory still
    supports phase 6's dependency graph, so discarding it would throw away usable work.
    PARTIAL rather than SUCCEEDED because phase 4 would otherwise compute churn over a
    truncated history and present the result as complete.

    The same reasoning covers analysis. A scan whose complexity could not be measured
    still has churn, and churn alone ranks something; reporting it as SUCCEEDED would
    present a churn-only ordering as the full risk model.
    """
    return ScanStatus.PARTIAL if (history_error or analysis_error) else ScanStatus.SUCCEEDED


async def _record_failure(
    session: AsyncSession, scan_id: uuid.UUID, reason: str, *, event: str
) -> None:
    """Mark a scan FAILED with its reason, from a path where the session may be dirty.

    Rolls back first. The exception may have left the transaction unusable, and a commit
    on a poisoned transaction raises again -- losing the reason at the exact moment the
    system is trying to record one. The scan is re-fetched rather than reused because a
    rollback expires every object in the session, and reading an expired attribute under
    asyncio is implicit lazy IO, which raises MissingGreenlet.
    """
    await session.rollback()
    scan = await session.get(Scan, scan_id)
    if scan is None:
        # Nothing left to record against; the log is the only place left to say so.
        logger.error(event, scan_id=str(scan_id), error=reason, scan_missing=True)
        return
    scan.status = ScanStatus.FAILED
    scan.error = reason
    scan.completed_at = datetime.now(UTC)
    await session.commit()
    logger.error(event, scan_id=str(scan_id), error=reason)


async def run_ingestion(session: AsyncSession, scan_id: uuid.UUID, *, settings: Settings) -> None:
    """Clone, inventory and mine the repository for ``scan_id``, recording the outcome."""
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise LookupError(f"No scan with id {scan_id}")

    repository = await session.get(Repository, scan.repository_id)
    if repository is None:
        raise LookupError(f"Scan {scan_id} references a repository that does not exist")

    scan.status = ScanStatus.RUNNING
    await session.commit()

    # Created rather than assumed. On a fresh deployment clone_root does not exist yet,
    # and mkdtemp would raise FileNotFoundError.
    #
    # The try is the lesson from the first real `docker compose up`. This mkdir was
    # already here, defending against exactly one exception type, under a comment saying
    # that anything escaping here "would strand the scan in RUNNING forever" -- and then
    # the next line raised PermissionError, which is not FileNotFoundError and is not an
    # IngestionError, and stranded the scan in RUNNING forever. Guarding a failure mode
    # one exception at a time is how that keeps happening.
    clone_root = Path(settings.clone_root)
    try:
        clone_root.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix="codesentinel-", dir=clone_root))
    except OSError as exc:
        # Reported with the path and the likely cause rather than as errno 13. An
        # operator reading "Permission denied" learns nothing they can act on; the
        # ownership of the volume is the thing to go and look at.
        await _record_failure(
            session,
            scan_id,
            f"The clone root {clone_root} is not usable by the user this process runs "
            f"as: {exc}. Under Docker this is usually a clones volume owned by root "
            f"while the container runs unprivileged -- the image must create and own "
            f"that directory so a named volume inherits the ownership.",
            event="scan.clone_root_unusable",
        )
        return
    clone_path = destination / "repo"

    try:
        result = clone_repository(repository.url, clone_path, settings=settings)
        scan.commit_sha = result.commit_sha
        if repository.default_branch is None:
            repository.default_branch = result.default_branch

        files_by_path = await _persist_inventory(session, repository, clone_path)
        history_error = await _persist_history(session, repository, clone_path, files_by_path)

        if history_error:
            # _persist_history rolled back, which expires every object in the session.
            # Reloading explicitly here keeps the attribute reads below from becoming
            # implicit lazy IO, which raises MissingGreenlet under asyncio.
            await session.refresh(scan)

        # Analysis runs here, before the finally deletes the clone. Radon reads the
        # working tree, and there is no second chance: a later stage would have to clone
        # the repository again.
        analysis_error = await run_analysis(
            session,
            scan_id=scan.id,
            repository_id=repository.id,
            clone_path=clone_path,
            files_by_path=files_by_path,
            # The scan's own start, not "now", so churn is reproducible on re-read (C5).
            as_of=scan.started_at,
            settings=settings,
        )

        scan.status = classify_outcome(history_error=history_error, analysis_error=analysis_error)
        statuses = dict(scan.analyzer_statuses)
        if history_error:
            statuses["ingestion"] = {"status": "partial", "error": history_error}
        if analysis_error:
            statuses[ANALYZER_NAME] = {"status": "partial", "error": analysis_error}
        if statuses != scan.analyzer_statuses:
            scan.analyzer_statuses = statuses
        scan.completed_at = datetime.now(UTC)
        await session.commit()
        logger.info("scan.done", scan_id=str(scan_id), status=scan.status)

    except IngestionError as exc:
        # An ingestion error is an ordinary, recordable outcome -- a repository that is
        # too large is not a fault in this system. The reason is stored so the caller
        # never has to read a log to find out why (anti-pattern #9).
        scan.status = ScanStatus.FAILED
        scan.error = str(exc)
        scan.completed_at = datetime.now(UTC)
        await session.commit()
        logger.warning("scan.failed", scan_id=str(scan_id), error=str(exc))

    # No `noqa: BLE001` needed: ruff permits a broad catch that re-raises, which is
    # exactly the shape this is -- record the reason, then let the exception carry on.
    except Exception as exc:
        # Everything the pipeline did not anticipate: a permission error, a dropped
        # connection, a bug in an analyser. What matters is that the scan does not stay
        # RUNNING. C3 requires a failure to carry its reason, and a row left in RUNNING
        # carries none, is indistinguishable from a scan still working, and is collected
        # by nothing -- the retention pruner skips non-terminal scans deliberately, so it
        # is there until somebody deletes it by hand.
        #
        # Re-raised immediately after recording. The reason reaches the caller through
        # the scan row and the traceback still reaches the worker log and Celery's own
        # failure reporting; this records the exception, it does not swallow it.
        await _record_failure(
            session,
            scan_id,
            f"{type(exc).__name__}: {exc}",
            event="scan.failed_unexpectedly",
        )
        raise

    finally:
        # remove_tree, not shutil.rmtree(ignore_errors=True): git leaves its objects
        # read-only, and a silently failed delete here accumulates whole clones under
        # clone_root -- on the failure path, which is where the big ones are.
        remove_tree(destination)


async def _persist_inventory(
    session: AsyncSession, repository: Repository, clone_path: Path
) -> dict[str, uuid.UUID]:
    """Write the file inventory and return a path -> id map for the history pass."""
    records = inventory_files(clone_path)
    files = [
        File(
            repository_id=repository.id,
            path=record.path,
            language=record.language,
            loc=record.loc,
            is_test=record.is_test,
        )
        for record in records
    ]
    session.add_all(files)
    await session.commit()
    return {file.path: file.id for file in files}


async def _persist_history(
    session: AsyncSession,
    repository: Repository,
    clone_path: Path,
    files_by_path: dict[str, uuid.UUID],
) -> str | None:
    """Write commits and their file changes. Returns a reason if it could not finish."""
    batch: list[Commit] = []
    try:
        for record in mine_history(clone_path):
            commit = Commit(
                repository_id=repository.id,
                sha=record.sha,
                author_email=record.author_email,
                authored_at=record.authored_at,
                message_summary=record.message_summary,
                files_changed=record.files_changed,
                lines_added=record.lines_added,
                lines_deleted=record.lines_deleted,
            )
            session.add(commit)
            for change in record.changes:
                session.add(
                    FileChange(
                        commit_id=commit.id,
                        # None when the path does not exist at HEAD. Recorded rather
                        # than dropped so churn is not understated on deleted files.
                        file_id=files_by_path.get(change.path),
                        path=change.path,
                        lines_added=change.lines_added,
                        lines_deleted=change.lines_deleted,
                        change_type=change.change_type,
                    )
                )
            batch.append(commit)
            if len(batch) >= COMMIT_BATCH_SIZE:
                await session.commit()
                batch.clear()
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - returned as the PARTIAL reason, not swallowed
        await session.rollback()
        logger.warning("history.incomplete", error=str(exc))
        return f"History mining did not complete: {exc}"
    return None
