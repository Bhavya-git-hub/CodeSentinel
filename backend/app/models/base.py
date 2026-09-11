"""Declarative base and shared column conventions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit naming convention so Alembic autogenerate produces stable, diffable names for
# constraints instead of database-assigned ones. Without this, a later migration that
# drops a constraint has no reliable name to reference.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Client-generated UUID primary keys, available the moment an instance exists.

    Generated in Python rather than by the database so a full object graph (scan ->
    files -> metrics -> findings, or a commit and its file_changes) can be built in
    memory and bulk-inserted in one round trip, which the ingestion pipeline needs.

    That promise is why ``__init__`` assigns the key rather than leaving it to the column
    default. ``default=uuid.uuid4`` alone is a *Core* default, evaluated during INSERT --
    so ``instance.id`` is still None while the graph is being assembled, and every caller
    that reads ``parent.id`` to populate a child's foreign key writes NULL instead. That
    failure is close to invisible: the pipeline catches the resulting IntegrityError,
    records the scan PARTIAL, and every commit and file change is silently lost.

    The column default is kept as well, for paths that bypass ``__init__`` entirely --
    ``bulk_insert_mappings`` and loads constructed by the ORM itself.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, sort_order=-100
    )

    def __init__(self, **kwargs: Any) -> None:
        """Assign a key up front unless the caller supplied one."""
        kwargs.setdefault("id", uuid.uuid4())
        super().__init__(**kwargs)


class CreatedAtMixin:
    """Server-side creation timestamp, always timezone-aware."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, sort_order=100
    )
