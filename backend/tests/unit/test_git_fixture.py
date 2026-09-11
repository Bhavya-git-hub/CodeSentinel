"""The git fixture repository is itself worth a test -- everything downstream trusts it."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_the_fixture_repo_has_three_commits(git_repo: Path, git_binary: str) -> None:
    log = subprocess.run(
        [git_binary, "log", "--format=%s"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert log.stdout.split() != []
    assert len(log.stdout.strip().splitlines()) == 3


def test_the_fixture_repo_url_is_a_file_url(git_repo_url: str) -> None:
    assert git_repo_url.startswith("file://")
