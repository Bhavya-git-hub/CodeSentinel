"""SZZ labelling.

The technique's failure mode is confidently labelling commits it guessed at, so the tests
are mostly about what it refuses to decide.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.prediction.szz import (
    BlameLine,
    CandidateCommit,
    classify_message,
    induce_from_blame,
    label_bugfixes,
)

NOW = datetime(2026, 9, 11, tzinfo=UTC)


@pytest.mark.parametrize(
    "summary",
    [
        "fix: crash when the queue is empty",
        "Fixed a bug in the parser",
        "hotfix for the login regression",
        "resolve #412",
        "closes #88",
    ],
)
def test_real_bug_fixes_are_recognised(summary: str) -> None:
    assert classify_message(summary).matched is True


@pytest.mark.parametrize(
    "summary",
    [
        "add a prefix to the log line",
        "rename suffix handling",
        "add a pytest fixture for the sandbox",
        "refactor the affix parser",
    ],
)
def test_substring_lookalikes_are_not_bug_fixes(summary: str) -> None:
    """Matching 'fix' as a substring catches prefix, suffix and fixture.

    Every false positive propagates: it blames whichever commits last touched those
    lines, and they become defect-inducing training examples for a change that fixed
    nothing.
    """
    assert classify_message(summary).matched is False


@pytest.mark.parametrize(
    "summary",
    [
        "fix typo in the readme",
        "fix formatting",
        "fix the docs for the scans endpoint",
        "fix lint",
    ],
)
def test_cosmetic_fixes_are_excluded(summary: str) -> None:
    """These fix no defect a model should learn from."""
    assert classify_message(summary).matched is False


def test_a_commit_with_no_message_is_undecided_not_negative() -> None:
    """Recording it as 'not a bug fix' would be a claim with no basis (C4)."""
    assert classify_message(None).matched is None
    assert classify_message("   ").matched is None


def test_undecided_commits_are_kept_apart_from_decided_negatives() -> None:
    """A pass reporting 860 negatives it never classified is actively misleading."""
    commits = [
        CandidateCommit("a" * 40, "fix: crash on empty input", NOW),
        CandidateCommit("b" * 40, "add the parser", NOW),
        CandidateCommit("c" * 40, None, NOW),
    ]

    bugfixes, undecided = label_bugfixes(commits)

    assert bugfixes == {"a" * 40}
    assert undecided == {"c" * 40}
    # "b" is a decided negative and appears in neither set.
    assert "b" * 40 not in bugfixes and "b" * 40 not in undecided


def test_only_commits_older_than_the_fix_are_blamed() -> None:
    """Labelling a later commit as inducing an earlier fix is a causality error.

    Blame can attribute a line to a commit newer than the fix when history has been
    rewritten, and the wrong label would quietly corrupt the training set.
    """
    older, newer = "1" * 40, "2" * 40
    blame = [BlameLine("pkg/a.py", 3, older), BlameLine("pkg/a.py", 4, newer)]
    dates = {older: NOW - timedelta(days=30), newer: NOW + timedelta(days=1)}

    assert induce_from_blame(blame, fix_authored_at=NOW, commit_dates=dates) == {older}


def test_a_blamed_commit_with_no_known_date_is_skipped() -> None:
    """Assuming it is older would invent the ordering the check exists to verify."""
    blame = [BlameLine("pkg/a.py", 3, "9" * 40)]
    assert induce_from_blame(blame, fix_authored_at=NOW, commit_dates={}) == set()


def test_a_merge_is_never_a_bug_fix() -> None:
    """A merge's message often carries the branch's fix wording without being the fix."""
    assert classify_message("Merge pull request #12 from fix/crash").matched is False
