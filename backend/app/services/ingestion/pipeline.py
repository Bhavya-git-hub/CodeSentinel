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
from app.services.ingestion.cloner import clone_repository, remove_tree
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.history import mine_history
from app.services.ingestion.inventory import inventory_files

logger = structlog.get_logger(__name__)

COMMIT_BATCH_SIZE = 500


def classify_outcome(*, history_error: str | None) -> ScanStatus:
    """The terminal status for a run whose clone and inventory both succeeded.

    PARTIAL rather than FAILED when history is incomplete: the file inventory still
    supports phase 6's dependency graph, so discarding it would throw away usable work.
    PARTIAL rather than SUCCEEDED because phase 4 would otherwise compute churn over a
    truncated history and present the result as complete.
    """
    return ScanStatus.PARTIAL if history_error else ScanStatus.SUCCEEDED


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
    # and mkdtemp would raise FileNotFoundError -- which is not an IngestionError, so it
    # would escape the handler below and strand the scan in RUNNING forever.
    clone_root = Path(settings.clone_root)
    clone_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="codesentinel-", dir=clone_root))
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

        scan.status = classify_outcome(history_error=history_error)
        if history_error:
            scan.analyzer_statuses = {
                **scan.analyzer_statuses,
                "ingestion": {"status": "partial", "error": history_error},
            }
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
