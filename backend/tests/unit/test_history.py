"""Parsing git history into commit records."""

from __future__ import annotations

from app.models.enums import ChangeType
from app.services.ingestion.history import parse_numstat_line


def test_a_text_change_carries_both_counts() -> None:
    record = parse_numstat_line("12\t3\tpkg/module.py")
    assert record is not None
    assert record.path == "pkg/module.py"
    assert record.lines_added == 12
    assert record.lines_deleted == 3
    assert record.change_type is ChangeType.MODIFIED


def test_a_binary_change_has_no_counts() -> None:
    """git prints '-' for a binary diff. That is unknown, not zero."""
    record = parse_numstat_line("-\t-\tlogo.png")
    assert record is not None
    assert record.lines_added is None
    assert record.lines_deleted is None


def test_an_added_file_is_classified_as_added() -> None:
    record = parse_numstat_line("7\t0\tpkg/new.py")
    assert record is not None
    assert record.change_type is ChangeType.ADDED


def test_a_deleted_file_is_classified_as_deleted() -> None:
    record = parse_numstat_line("0\t9\tpkg/gone.py")
    assert record is not None
    assert record.change_type is ChangeType.DELETED


def test_a_rename_records_the_new_path() -> None:
    """git's rename form is 'old => new'; churn belongs to where the file is now."""
    record = parse_numstat_line("1\t1\tpkg/{old.py => new.py}")
    assert record is not None
    assert record.path == "pkg/new.py"
    assert record.change_type is ChangeType.RENAMED


def test_a_bare_rename_without_braces_is_also_resolved() -> None:
    """git omits the braces when nothing in the path is common to both sides."""
    record = parse_numstat_line("2\t2\told/a.py => new/b.py")
    assert record is not None
    assert record.path == "new/b.py"
    assert record.change_type is ChangeType.RENAMED


def test_a_blank_line_is_not_a_change() -> None:
    assert parse_numstat_line("") is None
