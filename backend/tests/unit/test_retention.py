"""Retention: the pruning window, and what the scheduler advertises.

The deletion itself is exercised against a real PostgreSQL in
``tests/integration/test_retention_integration.py`` -- the whole point of the pruner is
that a foreign-key cascade reclaims the repository-scoped tables, and a cascade is a
property of the database rather than of this code.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.retention import RetentionDisabledError, prune_scans
from app.workers.celery_app import beat_schedule


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
