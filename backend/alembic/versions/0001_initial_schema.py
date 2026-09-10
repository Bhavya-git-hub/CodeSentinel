"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-11

Creates the full scan/commit/file grain in one revision. The tables interlock -- metrics
and findings are meaningless without scans and files, and the phase 4 and 8 features
depend on commits -- so splitting them across revisions would only produce a sequence
that is never valid to stop halfway through.

Hand-reviewed after autogeneration. Two corrections were required and are marked inline:
the timestamp server default, and the expression-based risk_score index that autogenerate
cannot render.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
        sa.UniqueConstraint("url", name=op.f("uq_repositories_url")),
    )
    op.create_table(
        "commits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("sha", sa.String(length=40), nullable=False),
        sa.Column("author_email", sa.String(length=320), nullable=True),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_summary", sa.Text(), nullable=True),
        sa.Column("files_changed", sa.Integer(), nullable=True),
        sa.Column("lines_added", sa.Integer(), nullable=True),
        sa.Column("lines_deleted", sa.Integer(), nullable=True),
        sa.Column("is_bugfix", sa.Boolean(), nullable=True),
        sa.Column("is_defect_inducing", sa.Boolean(), nullable=True),
        sa.Column("is_merge", sa.Boolean(), nullable=False),
        sa.Column("is_bulk_change", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_commits_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commits")),
        sa.UniqueConstraint("repository_id", "sha", name="uq_commits_repository_id_sha"),
    )
    op.create_index(
        "ix_commits_repository_id_authored_at",
        "commits",
        ["repository_id", "authored_at"],
        unique=False,
    )
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("loc", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_files_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("repository_id", "path", name="uq_files_repository_id_path"),
    )
    op.create_table(
        "scans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "partial",
                "failed",
                name="scan_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tool_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analyzer_statuses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_scans_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scans")),
    )
    op.create_index(
        "ix_scans_repository_id_started_at", "scans", ["repository_id", "started_at"], unique=False
    )
    op.create_table(
        "dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("target_file_id", sa.Uuid(), nullable=True),
        sa.Column("raw_module_name", sa.String(length=1024), nullable=False),
        sa.Column(
            "edge_type",
            sa.Enum(
                "import",
                "import_from",
                "relative_import",
                "dynamic",
                name="edge_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("unresolved_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.id"],
            name=op.f("fk_dependencies_scan_id_scans"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["files.id"],
            name=op.f("fk_dependencies_source_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_file_id"],
            ["files.id"],
            name=op.f("fk_dependencies_target_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dependencies")),
    )
    op.create_index(
        "ix_dependencies_scan_id_source_file_id",
        "dependencies",
        ["scan_id", "source_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_dependencies_scan_id_target_file_id",
        "dependencies",
        ["scan_id", "target_file_id"],
        unique=False,
    )
    op.create_table(
        "file_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("cyclomatic_complexity", sa.Float(), nullable=True),
        sa.Column("maintainability_index", sa.Float(), nullable=True),
        sa.Column("churn_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("normalized_complexity", sa.Float(), nullable=True),
        sa.Column("normalized_churn", sa.Float(), nullable=True),
        sa.Column("coverage_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            name=op.f("fk_file_metrics_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.id"],
            name=op.f("fk_file_metrics_scan_id_scans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file_metrics")),
        sa.UniqueConstraint("scan_id", "file_id", name="uq_file_metrics_scan_id_file_id"),
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("analyzer", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "minor",
                "major",
                "critical",
                name="severity",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_findings_file_id_files"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name=op.f("fk_findings_scan_id_scans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index("ix_findings_file_id", "findings", ["file_id"], unique=False)
    op.create_index(
        "ix_findings_scan_id_severity", "findings", ["scan_id", "severity"], unique=False
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("defect_probability", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["scans.id"], name=op.f("fk_predictions_scan_id_scans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
        sa.UniqueConstraint(
            "scan_id", "commit_sha", "model_version", name="uq_predictions_scan_commit_model"
        ),
    )
    op.create_index("ix_predictions_scan_id", "predictions", ["scan_id"], unique=False)

    # Backs the primary dashboard query (the risk-ranked review queue). Autogenerate
    # cannot render expression-based indexes, so this one is written by hand:
    # DESC because the queue reads highest-risk first, NULLS LAST because a file whose
    # risk could not be computed must not outrank a measured high-risk file (C3).
    op.create_index(
        "ix_file_metrics_scan_id_risk_score",
        "file_metrics",
        ["scan_id", sa.text("risk_score DESC NULLS LAST")],
        unique=False,
    )


def downgrade() -> None:
    # Reverse dependency order. Indexes and constraints are dropped with their tables.
    op.drop_table("predictions")
    op.drop_table("dependencies")
    op.drop_table("findings")
    op.drop_table("file_metrics")
    op.drop_table("scans")
    op.drop_table("files")
    op.drop_table("commits")
    op.drop_table("repositories")
