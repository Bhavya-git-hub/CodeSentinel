"""Schema invariants that encode the project's correctness constraints.

These assert properties of the model definitions themselves, so a future change that
quietly reintroduces a forbidden pattern fails here rather than in a report.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models import Base, Commit, Dependency, FileMetric, Finding, Scan
from app.models.enums import AnalyzerStatus, EdgeType, ScanStatus, Severity

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
        "dependencies",
        "predictions",
    }
