"""File inventory: what is in the tree, and what we could not determine about it."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from app.services.ingestion.inventory import (
    classify_language,
    count_lines,
    inventory_files,
    is_test_path,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("pkg/module.py", "python"),
        ("setup.pyi", "python"),
        ("README.md", "markdown"),
        ("data.json", "json"),
        ("Makefile", None),
        ("image.png", None),
    ],
)
def test_language_is_classified_by_extension(path: str, expected: str | None) -> None:
    assert classify_language(PurePosixPath(path)) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_a.py", True),
        ("pkg/tests/test_a.py", True),
        ("test_module.py", True),
        ("module_test.py", True),
        ("conftest.py", True),
        ("pkg/module.py", False),
        ("pkg/contest.py", False),
        ("latest/thing.py", False),
    ],
)
def test_test_files_are_identified(path: str, expected: bool) -> None:
    """Phase 6 intersects coverage with complexity; test code must not be scored as
    production code."""
    assert is_test_path(PurePosixPath(path)) is expected


def test_an_empty_file_has_zero_lines(tmp_path: Path) -> None:
    """Zero is a real measurement about a real empty file."""
    target = tmp_path / "empty.py"
    target.write_text("", encoding="utf-8")
    assert count_lines(target) == 0


def test_an_undecodable_file_has_no_line_count(tmp_path: Path) -> None:
    """None means 'we could not count', which is not the same fact as 0 (C3)."""
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\xff\xfe\x00binary\x00")
    assert count_lines(target) is None


def test_inventory_skips_the_git_directory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / "pkg.py").write_text("x = 1\n", encoding="utf-8")

    paths = {record.path for record in inventory_files(tmp_path)}
    assert paths == {"pkg.py"}


def test_inventory_reports_posix_paths(tmp_path: Path) -> None:
    """Paths are stored POSIX-style so a Windows-ingested repo matches a Linux one."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "c.py").write_text("x = 1\n", encoding="utf-8")

    assert [record.path for record in inventory_files(tmp_path)] == ["a/b/c.py"]
