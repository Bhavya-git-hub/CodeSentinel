"""Coverage, and the distinction it exists to protect.

A file with no coverage data is not a file with 0% coverage. The first is unknown; the
second claims tests exist and do not touch it. Phase 6 ranks high-risk untested code off
this number, so a fabricated 0 would invent a finding.
"""

from __future__ import annotations

import json

from app.models.enums import AnalyzerStatus
from app.services.analyzers.coverage import (
    describe_suite_failure,
    parse_coverage_json,
)
from app.services.sandbox.result import SandboxOutcome, SandboxResult


def completed(exit_code: int | None, stdout: str = "", stderr: str = "") -> SandboxResult:
    return SandboxResult(
        outcome=SandboxOutcome.COMPLETED,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=1.0,
    )


def test_a_passing_suite_is_not_a_failure() -> None:
    assert describe_suite_failure(completed(0)) is None


def test_a_repository_with_no_tests_is_skipped_with_that_reason() -> None:
    """Having no tests is a fact about the target, not a fault in this system."""
    reason = describe_suite_failure(completed(5))
    assert reason is not None
    assert "no tests" in reason


def test_missing_dependencies_are_explained_rather_than_guessed_at() -> None:
    """The sandbox has no network by design, so this is the common case, not an anomaly.

    The reason names the offline constraint so a reader does not conclude the target
    repository is broken.
    """
    reason = describe_suite_failure(completed(1, stderr="ModuleNotFoundError: no module 'httpx'"))
    assert reason is not None
    assert "no network" in reason
    assert "httpx" in reason


def test_a_timed_out_suite_is_reported_as_such() -> None:
    timed_out = SandboxResult(
        outcome=SandboxOutcome.TIMED_OUT,
        exit_code=None,
        stdout="",
        stderr="",
        duration_seconds=600.0,
    )
    reason = describe_suite_failure(timed_out)
    assert reason is not None
    assert "timeout" in reason.lower()


def test_percentages_are_read_per_file() -> None:
    payload = json.dumps(
        {
            "files": {
                "/workspace/pkg/module.py": {"summary": {"percent_covered": 83.3}},
                "./pkg/other.py": {"summary": {"percent_covered": 0.0}},
            }
        }
    )

    result = parse_coverage_json(payload)

    assert result.status is AnalyzerStatus.SUCCESS
    assert result.percentages == {"pkg/module.py": 83.3, "pkg/other.py": 0.0}


def test_a_measured_zero_is_kept_as_zero() -> None:
    """0% from a suite that ran is a real measurement and must survive.

    It is the counterpart of the None rule: absence must not become zero, and a real zero
    must not become absence.
    """
    payload = json.dumps({"files": {"a.py": {"summary": {"percent_covered": 0.0}}}})
    assert parse_coverage_json(payload).percentages["a.py"] == 0.0


def test_a_file_absent_from_the_report_is_simply_absent() -> None:
    """It stays unmeasured downstream rather than defaulting to zero."""
    payload = json.dumps({"files": {"a.py": {"summary": {"percent_covered": 50.0}}}})
    assert "b.py" not in parse_coverage_json(payload).percentages


def test_unparseable_coverage_output_fails_rather_than_reporting_nothing() -> None:
    result = parse_coverage_json("not json")
    assert result.status is AnalyzerStatus.FAILED
    assert result.percentages == {}
    assert result.error is not None


def test_a_skip_is_distinguishable_from_a_failure() -> None:
    """SKIPPED means it could not run; FAILED means it ran and broke. C3 needs both."""
    assert AnalyzerStatus.SKIPPED is not AnalyzerStatus.FAILED
