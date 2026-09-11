"""Retention: the pruning window, and what the scheduler advertises.

The deletion itself is exercised against a real PostgreSQL in
``tests/integration/test_retention_integration.py`` -- the whole point of the pruner is
that a foreign-key cascade reclaims the repository-scoped tables, and a cascade is a
property of the database rather than of this code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.retention import RetentionDisabledError, prune_scans
from app.workers.celery_app import beat_schedule


def _with_clone_root(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """Point the process-wide settings at this clone root, and put them back afterwards.

    Through the environment rather than a constructed Settings, because check_clone_root
    reads the cached get_settings() exactly as the worker does -- passing an object would
    exercise a path the worker never takes. monkeypatch reverts it: a leaked
    CODESENTINEL_CLONE_ROOT would silently redirect every later test in the process.
    """
    from app.config import get_settings

    monkeypatch.setenv("CODESENTINEL_CLONE_ROOT", path)
    get_settings.cache_clear()


async def test_a_retention_of_zero_is_refused_not_treated_as_a_cutoff_of_now() -> None:
    """Zero means disabled. The arithmetic for "0 days" deletes the entire history.

    This is the single most damaging way the function could be called wrongly, and the
    call site that does it would look completely ordinary, so the refusal lives here
    rather than relying on every caller to check.
    """
    with pytest.raises(RetentionDisabledError) as excinfo:
        await prune_scans(object(), retention_days=0)  # type: ignore[arg-type]

    assert "disabled" in str(excinfo.value)


async def test_a_negative_retention_is_refused_too() -> None:
    with pytest.raises(RetentionDisabledError):
        await prune_scans(object(), retention_days=-1)  # type: ignore[arg-type]


def test_retention_is_off_by_default() -> None:
    """An upgrade must not start deleting an operator's history unasked."""
    assert Settings().retention_days == 0


def test_nothing_is_scheduled_when_retention_is_off() -> None:
    """An operator reading the schedule must not conclude this deployment prunes."""
    assert beat_schedule(Settings(retention_days=0)) == {}


def test_the_pruning_job_is_scheduled_when_retention_is_on() -> None:
    schedule = beat_schedule(Settings(retention_days=30))

    assert "prune-expired-scans" in schedule
    assert schedule["prune-expired-scans"]["task"] == "codesentinel.prune_scans"


def test_the_schedule_honours_the_configured_interval() -> None:
    schedule = beat_schedule(Settings(retention_days=30, retention_interval_hours=6))

    assert schedule["prune-expired-scans"]["schedule"].total_seconds() == 6 * 3600


def test_retention_is_not_in_the_reproducibility_snapshot() -> None:
    """It changes what is kept, never what a scan computed.

    C5 records the configuration that produced a result. How long that result is then
    retained is not part of producing it, and putting it in the snapshot would imply two
    scans with different retention settings are not comparable.
    """
    snapshot = Settings(retention_days=30).reproducibility_snapshot()
    assert "retention_days" not in snapshot


# ---------------------------------------------------------------------------
# The worker's clone-root guard
#
# The first real deployment had the clone directory owned by root while the worker ran
# as uid 10001, so every scan died on the first mkdtemp. The pipeline records that as a
# FAILED scan with its reason, which is correct and still too late: the operator finds
# out one scan at a time, from the API, about a mistake that was already true before any
# work was accepted.
# ---------------------------------------------------------------------------


def test_a_usable_clone_root_lets_the_worker_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers.celery_app import check_clone_root

    root = tmp_path / "clones"
    _with_clone_root(monkeypatch, str(root))

    # Returns None; the assertion is that it does not raise, and that it created the
    # directory rather than demanding one already exist.
    check_clone_root()

    assert root.is_dir()


def test_an_unwritable_clone_root_stops_the_worker_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file where the directory should be: an OSError the worker must not survive.

    Chosen over chmod because this suite runs on Windows too, where mode bits do not deny
    a directory to its owner, so a permission test would pass by never failing.
    """
    from app.workers.celery_app import CloneRootUnusableError, check_clone_root

    blocker = tmp_path / "blocked"
    blocker.write_text("")
    _with_clone_root(monkeypatch, str(blocker / "clones"))

    with pytest.raises(CloneRootUnusableError) as excinfo:
        check_clone_root()

    message = str(excinfo.value)
    assert str(blocker / "clones") in message, "the reason must name the path"
    # The fix is a chown on the host, which an errno alone would never suggest.
    assert "chown" in message


def test_the_probe_file_is_not_left_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It would otherwise accumulate one file per worker restart, forever."""
    from app.workers.celery_app import check_clone_root

    root = tmp_path / "clones"
    _with_clone_root(monkeypatch, str(root))

    check_clone_root()

    assert list(root.iterdir()) == []


def test_the_guard_is_actually_wired_to_worker_start() -> None:
    """The function being correct is worth nothing if the signal never calls it.

    Every other test here invokes check_clone_root directly, so all of them would keep
    passing if the decorator were dropped -- and a worker with no guard looks exactly like
    a worker whose guard passed. This asserts the connection itself.
    """
    import weakref

    from celery.signals import worker_init

    connected = set()
    for receiver in worker_init.receivers:
        target = receiver[1] if isinstance(receiver, tuple) else receiver
        if isinstance(target, weakref.ref):
            target = target()
        name = getattr(target, "__name__", None)
        if name:
            connected.add(name)

    assert "check_clone_root" in connected, (
        f"the clone-root guard is not connected to worker_init; connected: {connected}"
    )
