"""History mining against a real repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ingestion.history import HistoryMiningError, mine_history

pytestmark = pytest.mark.usefixtures("git_binary")


def test_every_commit_is_mined_newest_first(git_repo: Path) -> None:
    commits = list(mine_history(git_repo))
    assert [c.message_summary for c in commits] == [
        "test: cover f",
        "feat: add g",
        "feat: add module",
    ]


def test_commits_carry_their_per_file_changes(git_repo: Path) -> None:
    commits = {c.message_summary: c for c in mine_history(git_repo)}
    changed = {change.path for change in commits["test: cover f"].changes}
    assert changed == {"tests/test_module.py"}


def test_authorship_and_timestamps_are_recorded(git_repo: Path) -> None:
    commit = next(iter(mine_history(git_repo)))
    assert commit.author_email == "fixture@example.com"
    assert commit.authored_at.tzinfo is not None, "timestamps must be timezone-aware"
    assert len(commit.sha) == 40


def test_a_failing_git_log_raises_rather_than_yielding_nothing(tmp_path: Path) -> None:
    """An empty history and an unreadable one must not look the same.

    A directory that is not a repository makes git exit non-zero. If that were swallowed,
    mine_history would yield no commits and the scan would record a target with no
    history at all -- which is a real state some repositories are in, so the two are
    indistinguishable downstream.
    """
    with pytest.raises(HistoryMiningError) as excinfo:
        list(mine_history(tmp_path))
    assert "git log exited" in str(excinfo.value)


def test_the_generator_is_lazy(git_repo: Path) -> None:
    """Nothing is read until the first record is asked for.

    The pipeline persists in batches so the memory ceiling is the batch, not the
    repository. A generator that eagerly buffered the whole log would still pass every
    other test here while reintroducing exactly the unbounded walk this avoids.
    """
    stream = mine_history(git_repo)
    first = next(stream)
    assert first.message_summary == "test: cover f"
    stream.close()
