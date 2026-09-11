"""Schema invariants that encode the project's correctness constraints.

These assert properties of the model definitions themselves, so a future change that
quietly reintroduces a forbidden pattern fails here rather than in a report.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models import Base, Commit, Dependency, FileChange, FileMetric, Finding, Scan
from app.models.enums import AnalyzerStatus, ChangeType, EdgeType, ScanStatus, Severity

NOW = datetime(2026, 9, 11, tzinfo=UTC)

METRIC_COLUMNS = (
    "cyclomatic_complexity",
    "maintainability_index",
    "churn_score",
    "risk_score",
    "normalized_complexity",
    "normalized_churn",
    "coverage_pct",
)


@pytest.mark.parametrize("column_name", METRIC_COLUMNS)
def test_every_metric_column_is_nullable(column_name: str) -> None:
    """Constraint C3 / anti-pattern #2: missing data must be representable.

    A file with no coverage data is not a file with 0% coverage. If these columns were
    NOT NULL DEFAULT 0 the distinction would be destroyed at write time and no downstream
    code could recover it.
    """
    column = FileMetric.__table__.columns[column_name]
    assert column.nullable, f"{column_name} must be nullable so 'not measured' is storable"
    assert column.default is None
    assert column.server_default is None


def test_risk_components_are_stored_alongside_the_product() -> None:
    """Phase 4: the dashboard must be able to explain why a file scored high."""
    columns = FileMetric.__table__.columns
    assert {"normalized_complexity", "normalized_churn", "risk_score"} <= set(columns.keys())


def test_review_queue_index_orders_descending_with_nulls_last() -> None:
    """The primary dashboard query reads highest-risk first.

    NULLS LAST matters: an unmeasured file must not sort above a measured high-risk one.
    """
    index = next(
        i for i in FileMetric.__table__.indexes if i.name == "ix_file_metrics_scan_id_risk_score"
    )
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "risk_score DESC NULLS LAST" in ddl
    assert "scan_id" in ddl


def test_commits_are_indexed_for_history_queries() -> None:
    names = {i.name for i in Commit.__table__.indexes}
    assert "ix_commits_repository_id_authored_at" in names


@pytest.mark.parametrize("column_name", ["is_bugfix", "is_defect_inducing"])
def test_defect_labels_are_tri_state(column_name: str) -> None:
    """Unlabelled is not the same as 'not a defect'.

    Defaulting these to False would inject unverified negative examples into the phase 8
    training set -- fabricated data, which constraint C4 forbids.
    """
    column = Commit.__table__.columns[column_name]
    assert column.nullable
    assert column.default is None


def test_unresolved_dependency_edges_are_representable() -> None:
    """Constraint C4: an unresolvable import is reported, not dropped."""
    columns = Dependency.__table__.columns
    assert columns["target_file_id"].nullable
    assert not columns["raw_module_name"].nullable
    assert EdgeType.DYNAMIC in set(EdgeType)


@pytest.mark.parametrize(
    ("model", "column_name", "expected"),
    [
        (Scan, "status", ScanStatus),
        (Finding, "severity", Severity),
        (Dependency, "edge_type", EdgeType),
    ],
)
def test_enum_columns_are_check_constrained(model: type, column_name: str, expected: type) -> None:
    """Non-native enums are only genuinely constrained if the CHECK is created.

    SQLAlchemy 2.x defaults ``create_constraint`` to False, which would leave the column
    accepting any string.
    """
    column = model.__table__.columns[column_name]
    assert column.type.native_enum is False
    assert column.type.create_constraint is True
    assert set(column.type.enums) == {member.value for member in expected}


def test_severity_scale_is_the_only_one() -> None:
    """Every adapter normalises onto this scale at its boundary."""
    assert [s.value for s in Severity] == ["info", "minor", "major", "critical"]


def test_analyzer_status_distinguishes_skipped_from_failed() -> None:
    """Constraint C3: a partial report must say which analyser did what, and why."""
    assert {s.value for s in AnalyzerStatus} == {"success", "failed", "skipped"}


def test_scan_status_can_express_partial_success() -> None:
    assert ScanStatus.PARTIAL in set(ScanStatus)


def test_scan_carries_the_full_reproducibility_record() -> None:
    """Constraint C5: commit SHA, tool versions and configuration, together."""
    columns = set(Scan.__table__.columns.keys())
    assert {"commit_sha", "tool_versions", "config"} <= columns


def test_scan_scoped_tables_cascade_from_scans() -> None:
    """A metric or finding has no meaning detached from the run that produced it."""
    for table in (FileMetric.__table__, Finding.__table__, Dependency.__table__):
        fk = next(fk for fk in table.foreign_keys if fk.column.table.name == "scans")
        assert fk.ondelete == "CASCADE", table.name


def test_all_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "repositories",
        "scans",
        "files",
        "file_metrics",
        "findings",
        "commits",
        "file_changes",
        "dependencies",
        "predictions",
    }


def test_a_file_change_may_reference_a_path_with_no_file_row() -> None:
    """A file touched in history may not exist at HEAD -- deleted, or renamed.

    Dropping those rows would understate churn on exactly the files that churned most
    (constraint C4: record the unresolvable rather than discarding it).
    """
    change = FileChange(
        commit_id=uuid.uuid4(),
        file_id=None,
        path="pkg/removed.py",
        lines_added=10,
        lines_deleted=3,
        change_type=ChangeType.DELETED,
    )
    assert change.file_id is None
    assert change.path == "pkg/removed.py"


def test_a_binary_file_change_has_no_line_counts() -> None:
    """git reports '-' for binary diffs; that is unknown, not zero."""
    change = FileChange(
        commit_id=uuid.uuid4(),
        file_id=None,
        path="logo.png",
        lines_added=None,
        lines_deleted=None,
        change_type=ChangeType.MODIFIED,
    )
    assert change.lines_added is None
    assert change.lines_deleted is None


def test_a_uuid_primary_key_exists_before_the_row_is_flushed() -> None:
    """The mixin promises in-memory object graphs; a flush-time default cannot deliver one.

    ``default=uuid.uuid4`` is a Core column default applied during INSERT, so the id is
    still None while the graph is being assembled. Every caller that reads ``parent.id``
    to populate a child's foreign key then writes NULL, and the row is rejected.
    """
    assert Commit(repository_id=uuid.uuid4(), sha="a" * 40, authored_at=NOW).id is not None


def test_a_child_built_from_its_parents_id_carries_a_real_key() -> None:
    """This is the shape pipeline._persist_history uses for every file change.

    It has to work without an intervening flush: the pipeline builds a commit and all of
    its file_changes in memory and inserts them together. A NULL here means the entire
    per-file churn history is silently lost and the scan degrades to PARTIAL.
    """
    commit = Commit(repository_id=uuid.uuid4(), sha="b" * 40, authored_at=NOW)

    change = FileChange(
        commit_id=commit.id,
        path="pkg/module.py",
        lines_added=1,
        lines_deleted=0,
        change_type=ChangeType.MODIFIED,
    )

    assert change.commit_id == commit.id
    assert change.commit_id is not None


def test_an_explicit_id_is_not_overwritten() -> None:
    """Callers that supply their own key must keep it."""
    chosen = uuid.uuid4()
    assert Commit(id=chosen, repository_id=uuid.uuid4(), sha="c" * 40, authored_at=NOW).id == chosen


def test_two_instances_do_not_share_a_key() -> None:
    first = Commit(repository_id=uuid.uuid4(), sha="d" * 40, authored_at=NOW)
    second = Commit(repository_id=uuid.uuid4(), sha="e" * 40, authored_at=NOW)
    assert first.id != second.id
