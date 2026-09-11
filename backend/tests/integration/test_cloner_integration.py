"""The cloner against a real git process.

Unit tests prove what configuration was requested; only these prove git honoured it.
Neither is sufficient alone -- a unit test can pass against a flag git ignores.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.ingestion import RepositoryTooLargeError, UnsafeRepositoryUrlError
from app.services.ingestion.cloner import clone_repository

pytestmark = pytest.mark.usefixtures("git_binary")


@pytest.fixture
def file_settings() -> Settings:
    return Settings(clone_allowed_protocols=["file"], max_repo_size_mb=64)


def test_a_repository_is_cloned_with_its_full_history(
    git_repo_url: str, tmp_path: Path, file_settings: Settings
) -> None:
    result = clone_repository(git_repo_url, tmp_path / "clone", settings=file_settings)

    assert result.path.is_dir()
    assert len(result.commit_sha) == 40
    assert (result.path / "pkg" / "module.py").is_file()

    from git import Repo

    assert len(list(Repo(result.path).iter_commits())) == 3, "history must not be shallow"


def test_an_oversized_repository_is_refused_and_removed(
    large_git_repo_url: str, tmp_path: Path
) -> None:
    """The limit is named in the error, and no partial tree is left behind."""
    settings = Settings(clone_allowed_protocols=["file"], max_repo_size_mb=1)
    destination = tmp_path / "clone"

    with pytest.raises(RepositoryTooLargeError) as excinfo:
        clone_repository(large_git_repo_url, destination, settings=settings)

    assert "1 MB" in str(excinfo.value)
    assert not destination.exists(), "the partial clone must be removed"


def test_a_disallowed_transport_never_starts_a_process(
    tmp_path: Path, file_settings: Settings
) -> None:
    with pytest.raises(UnsafeRepositoryUrlError):
        clone_repository("ext::sh -c whoami", tmp_path / "clone", settings=file_settings)
    assert not (tmp_path / "clone").exists()


@pytest.mark.skipif(
    "os.name != 'posix'", reason="Windows mode bits do not describe container access"
)
def test_the_clone_is_world_readable(
    git_repo_url: str, tmp_path: Path, file_settings: Settings
) -> None:
    """Phase 2's obligation: the sandbox uid must be able to read what we cloned."""
    result = clone_repository(git_repo_url, tmp_path / "clone", settings=file_settings)
    assert result.path.stat().st_mode & 0o005, "directory must be world read+execute"
    assert (result.path / "pkg" / "module.py").stat().st_mode & 0o004
