"""Scan lifecycle. The services are stubbed; what is under test is the bookkeeping."""

from __future__ import annotations

from app.models.enums import ScanStatus
from app.services.ingestion import RepositoryTooLargeError
from app.services.ingestion.pipeline import classify_outcome


def test_a_complete_run_succeeds() -> None:
    assert classify_outcome(history_error=None) is ScanStatus.SUCCEEDED


def test_incomplete_history_is_partial_not_failed() -> None:
    """The inventory is still usable; discarding it would throw away real work, and
    calling it SUCCEEDED would let phase 4 present truncated churn as complete."""
    assert classify_outcome(history_error="git log exited 128") is ScanStatus.PARTIAL


def test_a_refused_clone_fails_with_the_reason_named() -> None:
    error = RepositoryTooLargeError("The repository is 5000 MB, which exceeds the 1024 MB limit.")
    assert "1024 MB" in str(error)
