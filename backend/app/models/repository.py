"""Target repositories and their scans."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ScanStatus, enum_column

if TYPE_CHECKING:
    from app.models.code import File
    from app.models.history import Commit


class Repository(UUIDPrimaryKeyMixin, Base):
    """A public Git repository that has been submitted for analysis."""

    __tablename__ = "repositories"

    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scans: Mapped[list[Scan]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    files: Mapped[list[File]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    commits: Mapped[list[Commit]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class Scan(UUIDPrimaryKeyMixin, Base):
    """One analysis run against one commit of one repository.

    ``commit_sha``, ``tool_versions`` and ``config`` together are the reproducibility
    record required by constraint C5: they state exactly what was analysed, with which
    tool versions, under which settings.

    ``analyzer_statuses`` carries per-analyser outcome and failure reason so a partial
    report is self-describing (constraint C3). Its shape is
    ``{"pylint": {"status": "failed", "error": "...", "version": "3.3.1"}}``.
    """

    __tablename__ = "scans"
    __table_args__ = (Index("ix_scans_repository_id_started_at", "repository_id", "started_at"),)

    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    #: Nullable only while the scan is PENDING -- the SHA is not known until the clone
    #: resolves the ref. It is required for any terminal status.
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[ScanStatus] = mapped_column(
        enum_column(ScanStatus, "scan_status"),
        nullable=False,
        default=ScanStatus.PENDING,
    )
    #: Free-text reason a scan reached FAILED. Never a bare exception with no context
    #: (anti-pattern #9).
    error: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tool_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    analyzer_statuses: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Snapshot of ``Settings.reproducibility_snapshot()`` at dispatch time.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    repository: Mapped[Repository] = relationship(back_populates="scans")
