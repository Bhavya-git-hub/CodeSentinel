"""Version-control history and defect prediction.

These tables carry the data that distinguishes CodeSentinel from a linter: what changed,
when, by whom, and which changes introduced defects.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.repository import Repository


class Commit(UUIDPrimaryKeyMixin, Base):
    """One non-merge commit from the target repository's history.

    Both label columns are tri-state (``True`` / ``False`` / ``NULL``) rather than boolean
    defaults. ``NULL`` means "not yet labelled" -- the SZZ pass has not run, or ran and
    could not decide. Defaulting an unlabelled commit to ``False`` would silently inject
    negative training examples into the phase 8 dataset, which is exactly the kind of
    fabricated data constraint C4 forbids.
    """

    __tablename__ = "commits"
    __table_args__ = (
        UniqueConstraint("repository_id", "sha", name="uq_commits_repository_id_sha"),
        Index("ix_commits_repository_id_authored_at", "repository_id", "authored_at"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    author_email: Mapped[str | None] = mapped_column(String(320))
    authored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_summary: Mapped[str | None] = mapped_column(Text)

    files_changed: Mapped[int | None] = mapped_column(Integer)
    lines_added: Mapped[int | None] = mapped_column(Integer)
    lines_deleted: Mapped[int | None] = mapped_column(Integer)

    #: True when the commit message matched the conservative bug-fix indicators.
    is_bugfix: Mapped[bool | None] = mapped_column(Boolean)
    #: True when SZZ blamed this commit for lines later changed by a bug-fix commit.
    is_defect_inducing: Mapped[bool | None] = mapped_column(Boolean)

    #: Merge commits are excluded from churn (they would credit every file in the merge)
    #: and from the training set, but are still recorded so the history is complete.
    is_merge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Set for bulk-reformatting commits (a Black migration, a license header sweep) that
    #: touch an anomalously high fraction of files. Excluded from churn, and which commits
    #: were excluded is reported rather than silently dropped.
    is_bulk_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(255))

    repository: Mapped[Repository] = relationship(back_populates="commits")


class Prediction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A defect-risk score for one commit, from one version of the model.

    ``model_version`` is part of the reproducibility record (C5): a probability is not
    interpretable without knowing which model, trained on which data, produced it.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "scan_id", "commit_sha", "model_version", name="uq_predictions_scan_commit_model"
        ),
        Index("ix_predictions_scan_id", "scan_id"),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    defect_probability: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
