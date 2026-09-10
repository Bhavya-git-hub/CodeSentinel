"""Per-file analysis results: metrics, findings, and import edges."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import EdgeType, Severity, enum_column

if TYPE_CHECKING:
    from app.models.repository import Repository


class File(UUIDPrimaryKeyMixin, Base):
    """A source file, identified by its path within a repository.

    Rows persist across scans so history-derived metrics can be attached to a stable
    identity. ``is_deleted`` marks a file absent from the currently scanned tree rather
    than removing the row, because its churn and defect history remain meaningful.
    """

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("repository_id", "path", name="uq_files_repository_id_path"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32))
    #: Physical lines of code. NULL means "not counted", not "empty file".
    loc: Mapped[int | None] = mapped_column(Integer)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: True when the file was classified as a test module; phase 6 intersects the blast
    #: radius with this set to answer "which tests must re-run?".
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    repository: Mapped[Repository] = relationship(back_populates="files")


class FileMetric(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Per-file metrics for one scan.

    **Every metric column is nullable, deliberately.** Constraint C3 and anti-pattern #2
    forbid substituting 0 for missing data: a file with no coverage data is not a file
    with 0% coverage, and a file Radon could not parse is not a file of complexity 0.
    ``NOT NULL DEFAULT 0`` would erase that distinction at the storage layer and there
    would be no way to recover it downstream.

    ``normalized_complexity`` and ``normalized_churn`` are stored alongside their product
    so the dashboard can explain *why* a file ranks where it does, rather than presenting
    an unaccountable score.
    """

    __tablename__ = "file_metrics"
    __table_args__ = (
        UniqueConstraint("scan_id", "file_id", name="uq_file_metrics_scan_id_file_id"),
        # Backs the primary dashboard query: the risk-ranked review queue for a scan.
        # NULLS LAST because an unmeasured file must not outrank a measured high-risk one.
        Index("ix_file_metrics_scan_id_risk_score", "scan_id", text("risk_score DESC NULLS LAST")),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )

    cyclomatic_complexity: Mapped[float | None] = mapped_column()
    #: Radon's maintainability index, clamped to 0-100 (its raw formula can go negative).
    maintainability_index: Mapped[float | None] = mapped_column()
    #: Recency-weighted churn, exponentially decayed (phase 4).
    churn_score: Mapped[float | None] = mapped_column()
    risk_score: Mapped[float | None] = mapped_column()
    normalized_complexity: Mapped[float | None] = mapped_column()
    normalized_churn: Mapped[float | None] = mapped_column()
    coverage_pct: Mapped[float | None] = mapped_column()


class Finding(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A single issue reported by one analyser.

    ``severity`` is always on the normalised scale. Each adapter maps its tool's native
    vocabulary at the adapter boundary; Pylint and Bandit severity names never reach here.
    """

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_scan_id_severity", "scan_id", "severity"),
        Index("ix_findings_file_id", "file_id"),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    #: NULL for project-level findings that belong to no single file.
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("files.id", ondelete="CASCADE")
    )
    analyzer: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        enum_column(Severity, "severity", length=16),
        nullable=False,
    )
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class Dependency(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A directed import edge discovered by the phase 6 AST walk.

    ``target_file_id`` is nullable and paired with ``resolved``: constraint C4 requires an
    import that cannot be resolved to a repository file to be *reported as unresolved*,
    not dropped. ``raw_module_name`` preserves what the code actually asked for, so an
    unresolved edge still carries information (a dynamic ``importlib`` call, a third-party
    package, or a genuine resolution bug).
    """

    __tablename__ = "dependencies"
    __table_args__ = (
        Index("ix_dependencies_scan_id_source_file_id", "scan_id", "source_file_id"),
        Index("ix_dependencies_scan_id_target_file_id", "scan_id", "target_file_id"),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    target_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("files.id", ondelete="CASCADE")
    )
    raw_module_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    edge_type: Mapped[EdgeType] = mapped_column(
        enum_column(EdgeType, "edge_type"),
        nullable=False,
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Why resolution failed, when it did -- surfaced in the report rather than swallowed.
    unresolved_reason: Mapped[str | None] = mapped_column(String(255))
