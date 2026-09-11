"""SZZ against a real git repository.

The unit tests prove the parsers handle the shapes git is documented to emit. Only this
proves git emits them -- a parser can be perfectly correct about output no tool produces.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.prediction.blame import blame_suspects, changed_line_ranges
from app.services.prediction.szz import classify_message

pytestmark = pytest.mark.usefixtures("git_binary")


def _sha(repo: Path, git_binary: str, ref: str) -> str:
    return subprocess.run(
        [git_binary, "rev-parse", ref],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_the_fix_commit_is_recognised_as_one(git_repo_with_fix: Path, git_binary: str) -> None:
    summary = subprocess.run(
        [git_binary, "log", "-1", "--format=%s"],
        cwd=git_repo_with_fix,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert classify_message(summary).matched is True


def test_the_changed_range_is_read_from_a_real_diff(
    git_repo_with_fix: Path, git_binary: str
) -> None:
    ranges = changed_line_ranges(git_repo_with_fix, _sha(git_repo_with_fix, git_binary, "HEAD"))

    assert "pkg/buggy.py" in ranges
    # The fix replaced line 2, so the parent-side range must cover it.
    assert any(start <= 2 <= end for start, end in ranges["pkg/buggy.py"])


def test_blame_names_the_commit_that_introduced_the_defect(
    git_repo_with_fix: Path, git_binary: str
) -> None:
    """The whole technique in one assertion.

    The commit that wrote `return x / 0` must be blamed; the fix must not blame itself.
    """
    fix = _sha(git_repo_with_fix, git_binary, "HEAD")
    introducer = _sha(git_repo_with_fix, git_binary, "HEAD~1")

    suspects = blame_suspects(git_repo_with_fix, fix)

    assert introducer in suspects
    assert fix not in suspects


def test_a_root_commit_has_nothing_before_it_to_blame(
    git_repo_with_fix: Path, git_binary: str
) -> None:
    """There is no parent, so there is no earlier commit that could have caused anything."""
    root = subprocess.run(
        [git_binary, "rev-list", "--max-parents=0", "HEAD"],
        cwd=git_repo_with_fix,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert blame_suspects(git_repo_with_fix, root) == set()
