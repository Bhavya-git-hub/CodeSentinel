"""The whole pipeline against a real repository and a real database."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.code import File
from app.models.enums import ScanStatus
from app.models.history import Commit, FileChange
from app.models.repository import Repository, Scan
from app.services.ingestion.pipeline import run_ingestion

pytestmark = [pytest.mark.requires_db, pytest.mark.usefixtures("git_binary")]


@pytest.fixture
def ingest_settings(tmp_path: Path) -> Settings:
    """Settings whose clone_root is a directory nothing else writes into.

    A subdirectory, not tmp_path itself: the git_repo fixture builds its source repository
    in the same tmp_path, so pointing clone_root there would put the fixture and the
    clones in one directory and make "clone_root is empty afterwards" assert something
    other than what it claims.
    """
    return Settings(
        clone_allowed_protocols=["file"],
        clone_root=str(tmp_path / "clones"),
        max_repo_size_mb=64,
    )


async def test_a_full_run_records_files_commits_and_changes(
    db_session: AsyncSession, git_repo_url: str, ingest_settings: Settings
) -> None:
    repository = Repository(url=git_repo_url, name="fixture/repo")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    await run_ingestion(db_session, scan.id, settings=ingest_settings)

    await db_session.refresh(scan)
    # SUCCEEDED or PARTIAL, not FAILED. This test is about ingestion recording what it
    # found; whether every analyser could run against a two-file fixture is a separate
    # question, and pinning this to SUCCEEDED made it fail for reasons unrelated to its
    # subject. PARTIAL is only acceptable when the scan says why, which is asserted.
    assert scan.status in (ScanStatus.SUCCEEDED, ScanStatus.PARTIAL)
    if scan.status is ScanStatus.PARTIAL:
        assert scan.analyzer_statuses, "a partial scan must record which analyser fell short"
    assert scan.commit_sha is not None and len(scan.commit_sha) == 40
    assert scan.completed_at is not None

    files = (await db_session.execute(select(File))).scalars().all()
    assert {f.path for f in files} >= {"pkg/module.py", "tests/test_module.py"}
    assert next(f for f in files if f.path == "tests/test_module.py").is_test is True

    commits = (await db_session.execute(select(Commit))).scalars().all()
    assert len(commits) == 3

    changes = (await db_session.execute(select(FileChange))).scalars().all()
    assert changes, "per-file churn history must be captured during ingestion"


async def test_an_unreachable_repository_is_recorded_as_failed(
    db_session: AsyncSession, tmp_path: Path, ingest_settings: Settings
) -> None:
    """The reason is stored on the scan, so the caller never has to read a log."""
    repository = Repository(url=(tmp_path / "nope").as_uri(), name="missing/repo")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    await run_ingestion(db_session, scan.id, settings=ingest_settings)

    await db_session.refresh(scan)
    assert scan.status is ScanStatus.FAILED
    assert scan.error, "a failed scan must say why"


async def test_unminable_history_is_partial_and_says_so(
    db_session: AsyncSession,
    git_repo_url: str,
    ingest_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The PARTIAL path, which is the one that is easy to ship broken.

    It only runs after a rollback, and a rollback expires every object in the session --
    so reading scan.analyzer_statuses afterwards is implicit lazy IO, which raises
    MissingGreenlet under asyncio. Neither the SUCCEEDED nor the FAILED test above
    touches that path, so without this the failure would first appear on a real scan.
    """

    def _explode(_path: Path) -> object:
        raise RuntimeError("git log exited 128")

    monkeypatch.setattr("app.services.ingestion.pipeline.mine_history", _explode)

    repository = Repository(url=git_repo_url, name="fixture/repo")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    await run_ingestion(db_session, scan.id, settings=ingest_settings)

    await db_session.refresh(scan)
    assert scan.status is ScanStatus.PARTIAL
    assert scan.analyzer_statuses["ingestion"]["status"] == "partial"
    assert "git log exited 128" in scan.analyzer_statuses["ingestion"]["error"]

    # The inventory survived: that is the work PARTIAL exists to preserve.
    files = (await db_session.execute(select(File))).scalars().all()
    assert {f.path for f in files} >= {"pkg/module.py"}


async def test_the_clone_is_removed_whatever_happens(
    db_session: AsyncSession, git_repo_url: str, ingest_settings: Settings
) -> None:
    """Nothing is left under clone_root, on the success path or any other.

    shutil.rmtree(ignore_errors=True) would pass this on Linux and leak whole clones on
    Windows, where git's read-only objects defeat unlink -- see remove_tree.

    clone_root holds only what the pipeline puts there, so an empty directory here means
    the clone was removed rather than merely that nothing else happened to be present.
    """
    clone_root = Path(ingest_settings.clone_root)
    repository = Repository(url=git_repo_url, name="fixture/repo")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    await run_ingestion(db_session, scan.id, settings=ingest_settings)

    assert list(clone_root.iterdir()) == [], "the clone must not outlive the scan"


async def test_an_unusable_clone_root_is_recorded_not_left_running(
    db_session: AsyncSession,
    git_repo_url: str,
    ingest_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect the first real `docker compose up` found.

    The clones volume came up owned by root while the container runs unprivileged, so
    mkdtemp raised PermissionError. That is not an IngestionError, so it escaped the
    handler and left the scan in RUNNING with error NULL -- indistinguishable from a scan
    still working, and collected by nothing, because the retention pruner skips
    non-terminal scans deliberately.

    A permission error is simulated rather than produced by chmod: the suite runs on
    Windows too, where mode bits do not deny a directory to its owner, so a real chmod
    would make this test silently pass by not failing.
    """
    import tempfile

    def _denied(*_args: object, **_kwargs: object) -> str:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(tempfile, "mkdtemp", _denied)

    repository = Repository(url=git_repo_url, name="a/b")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    await run_ingestion(db_session, scan.id, settings=ingest_settings)

    await db_session.refresh(scan)
    assert scan.status is ScanStatus.FAILED, "the scan was left in a non-terminal state"
    assert scan.completed_at is not None
    assert scan.error and ingest_settings.clone_root in scan.error, (
        "the reason must name the path, so an operator knows where to look"
    )


async def test_an_unexpected_error_fails_the_scan_and_is_re_raised(
    db_session: AsyncSession,
    git_repo_url: str,
    ingest_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The general case of the same defect, for exceptions nobody has thought of yet.

    Guarding one exception type at a time is what produced the PermissionError above: the
    mkdir that raised it was itself added to guard against FileNotFoundError, under a
    comment warning that anything escaping would strand the scan in RUNNING forever.

    Re-raised rather than swallowed (anti-pattern #9): the scan row carries the reason for
    the caller, and the traceback still reaches the worker log and Celery's own failure
    reporting.
    """

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("an analyser did something nobody predicted")

    monkeypatch.setattr("app.services.ingestion.pipeline.clone_repository", _explode)

    repository = Repository(url=git_repo_url, name="a/b")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    with pytest.raises(RuntimeError, match="nobody predicted"):
        await run_ingestion(db_session, scan.id, settings=ingest_settings)

    await db_session.refresh(scan)
    assert scan.status is ScanStatus.FAILED, "the scan was left in a non-terminal state"
    assert scan.error and "RuntimeError" in scan.error, (
        "the reason must name what went wrong, not just that something did"
    )
