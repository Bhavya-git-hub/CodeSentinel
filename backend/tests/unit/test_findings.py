"""Pylint and Bandit adapters.

The trap both share: a non-zero exit means "I found something", not "I broke". A parser
that reads the exit status as a success flag discards every useful run.
"""

from __future__ import annotations

import json

import pytest

from app.models.enums import Severity
from app.services.analyzers.findings import (
    bandit_failed,
    parse_bandit,
    parse_pylint,
    pylint_failed,
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


# -- Pylint exit-status semantics -------------------------------------------------


@pytest.mark.parametrize("code", [2, 4, 8, 16, 4 | 16, 2 | 8])
def test_pylint_finding_problems_is_not_a_failure(code: int) -> None:
    """Pylint's exit status is a bitmask of what it found.

    2 error, 4 warning, 8 refactor, 16 convention. Treating any non-zero exit as a tool
    failure would throw away every run that found something -- that is, every useful run.
    """
    assert pylint_failed(completed(code)) is None


def test_pylint_exit_zero_is_not_a_failure() -> None:
    assert pylint_failed(completed(0)) is None


def test_a_pylint_fatal_is_a_failure() -> None:
    assert pylint_failed(completed(1, stderr="cannot import x")) is not None


def test_a_pylint_usage_error_is_a_failure() -> None:
    """Bit 5 means we invoked it wrongly, so its output says nothing about the target."""
    assert pylint_failed(completed(32, stderr="unrecognized option")) is not None


def test_a_killed_pylint_container_is_a_failure() -> None:
    """exit_code is None when the container never exited on its own."""
    timed_out = SandboxResult(
        outcome=SandboxOutcome.TIMED_OUT,
        exit_code=None,
        stdout="",
        stderr="",
        duration_seconds=600.0,
    )
    assert pylint_failed(timed_out) is not None


# -- Pylint parsing ---------------------------------------------------------------


def test_pylint_messages_are_mapped_onto_the_normalised_scale() -> None:
    payload = json.dumps(
        [
            {
                "type": "error",
                "message-id": "E1101",
                "message": "Instance of 'X' has no 'y' member",
                "path": "/workspace/pkg/module.py",
                "line": 12,
            },
            {
                "type": "convention",
                "message-id": "C0114",
                "message": "Missing module docstring",
                "path": "/workspace/pkg/other.py",
                "line": 1,
            },
        ]
    )

    result = parse_pylint(payload)

    assert [f.severity for f in result.findings] == [Severity.MAJOR, Severity.INFO]
    assert result.findings[0].path == "pkg/module.py"
    assert result.findings[0].rule_id == "E1101"
    assert result.error is None


def test_style_never_outranks_a_probable_bug() -> None:
    """A missing docstring must not sort above an attribute error."""
    payload = json.dumps(
        [
            {"type": "convention", "message-id": "C0114", "message": "m", "path": "a.py"},
            {"type": "error", "message-id": "E1101", "message": "m", "path": "a.py"},
        ]
    )
    severities = [f.severity for f in parse_pylint(payload).findings]
    assert severities[1] is Severity.MAJOR
    assert severities[0] is Severity.INFO


def test_pylint_with_nothing_to_say_produces_no_findings_and_no_error() -> None:
    """Pylint prints nothing at all when clean. That is a clean run, not a broken one."""
    result = parse_pylint("")
    assert result.findings == []
    assert result.error is None


def test_unparseable_pylint_output_is_an_error_not_an_empty_result() -> None:
    """An analyser that produced nothing and one that broke are different facts (C3)."""
    result = parse_pylint("<<not json>>")
    assert result.findings == []
    assert result.error is not None


# -- Bandit ------------------------------------------------------------------------


def test_bandit_exit_one_means_it_found_something() -> None:
    assert bandit_failed(completed(1)) is None


def test_bandit_exit_two_is_a_failure() -> None:
    assert bandit_failed(completed(2, stderr="boom")) is not None


def test_bandit_severity_is_normalised_and_confidence_is_kept() -> None:
    payload = json.dumps(
        {
            "results": [
                {
                    "test_id": "B602",
                    "issue_severity": "HIGH",
                    "issue_confidence": "LOW",
                    "issue_text": "subprocess call with shell=True",
                    "filename": "/workspace/pkg/run.py",
                    "line_number": 9,
                }
            ],
            "errors": [],
        }
    )

    result = parse_bandit(payload)
    finding = result.findings[0]

    assert finding.severity is Severity.CRITICAL
    assert finding.rule_id == "B602"
    assert finding.path == "pkg/run.py"
    # Confidence rides in the message rather than discounting the severity: a
    # low-confidence critical is still a critical someone should look at.
    assert "confidence: low" in finding.message


def test_files_bandit_could_not_scan_are_reported() -> None:
    """Omitting them would claim coverage of files nobody scanned."""
    payload = json.dumps(
        {
            "results": [],
            "errors": [{"filename": "/workspace/broken.py", "reason": "syntax error"}],
        }
    )

    result = parse_bandit(payload)

    assert result.findings == []
    assert result.error is not None
    assert "broken.py" in result.error


def test_bandit_silence_is_an_error_because_it_always_prints_json() -> None:
    """Unlike Pylint, Bandit emits a JSON envelope even with no findings."""
    assert parse_bandit("").error is not None
