"""The cloner's requested configuration, provable without a network."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.ingestion import RepositoryTooLargeError
from app.services.ingestion.cloner import (
    build_clone_command,
    directory_size_bytes,
    remove_tree,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(clone_allowed_protocols=["https"], max_repo_size_mb=1)


def test_the_clone_is_never_shallow(settings: Settings) -> None:
    """Phase 4 churn and phase 8 SZZ both need the complete commit graph."""
    command = build_clone_command("https://example.com/a/b", Path("/tmp/dest"), settings=settings)
    assert "--depth" not in " ".join(command)


def test_submodules_are_not_followed(settings: Settings) -> None:
    """A submodule pulls further untrusted content outside the size budget."""
    assert "--no-recurse-submodules" in build_clone_command(
        "https://example.com/a/b", Path("/tmp/dest"), settings=settings
    )


@pytest.mark.parametrize(
    "expected",
    [
        "protocol.allow=never",
        "protocol.https.allow=always",
        "core.symlinks=false",
    ],
)
def test_the_hardening_config_is_requested(expected: str, settings: Settings) -> None:
    assert expected in build_clone_command(
        "https://example.com/a/b", Path("/tmp/dest"), settings=settings
    )


def test_the_url_is_passed_after_a_double_dash(settings: Settings) -> None:
    """So a URL that survived validation still cannot be read as an option."""
    command = build_clone_command("https://example.com/a/b", Path("/tmp/d"), settings=settings)
    assert "--" in command
    assert command.index("--") < command.index("https://example.com/a/b")


def test_directory_size_counts_nested_files(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 100)
    nested = tmp_path / "deep"
    nested.mkdir()
    (nested / "b").write_bytes(b"y" * 50)
    assert directory_size_bytes(tmp_path) == 150


def test_size_error_names_the_limit_and_the_measurement() -> None:
    error = RepositoryTooLargeError(
        "The repository exceeded the 1 MB limit (measured 3 MB) and was not cloned."
    )
    assert "1 MB" in str(error)
    assert "3 MB" in str(error)


def test_a_read_only_tree_is_still_removed(tmp_path: Path) -> None:
    """git writes its objects read-only, and a partial clone is full of them.

    On Windows unlink needs the file itself writable; on POSIX it needs the parent
    directory writable. This fixture is unremovable by a naive rmtree on both, so the
    test fails on either platform if the handler regresses.
    """
    tree = tmp_path / "clone"
    nested = tree / ".git" / "objects"
    nested.mkdir(parents=True)
    payload = nested / "pack.idx"
    payload.write_bytes(b"objects are immutable")
    payload.chmod(0o444)
    nested.chmod(0o555)

    assert remove_tree(tree) is True
    assert not tree.exists()


def test_a_removal_that_fails_reports_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cleanup that silently 'succeeds' is how a disk fills up unnoticed.

    The sandbox logs a container it could not remove rather than swallowing it
    (runner.py); a clone we could not delete is the same leak and gets the same
    treatment, so the return value has to distinguish the two outcomes.
    """
    tree = tmp_path / "clone"
    tree.mkdir()

    def _always_fails(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("held open by another process")

    monkeypatch.setattr("app.services.ingestion.cloner.shutil.rmtree", _always_fails)

    assert remove_tree(tree) is False
