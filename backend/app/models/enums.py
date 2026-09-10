"""Enumerations shared across the data model.

Stored as VARCHAR with a CHECK constraint rather than native PostgreSQL enums: adding a
value later is then an ordinary migration instead of an ``ALTER TYPE`` that cannot run
inside a transaction. See docs/adr/0002.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class ScanStatus(StrEnum):
    """Lifecycle of a single scan."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    #: At least one analyser failed or was skipped but a report was still produced.
    #: Constraint C3 requires this to be distinguishable from a clean success.
    PARTIAL = "partial"
    FAILED = "failed"


class AnalyzerStatus(StrEnum):
    """Per-analyser outcome recorded on ``scans.analyzer_statuses``.

    ``SKIPPED`` means the analyser could not run (for example a target whose test suite
    will not install offline); it never means "ran and found nothing".
    """

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class Severity(StrEnum):
    """The single normalised severity scale.

    Every analyser adapter maps its tool's native vocabulary onto this scale at the
    adapter boundary. Pylint's and Bandit's own severity names must not appear past
    that point.
    """

    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class EdgeType(StrEnum):
    """Kind of dependency edge in the phase 6 import graph."""

    #: ``import x``
    IMPORT = "import"
    #: ``from x import y``
    IMPORT_FROM = "import_from"
    #: ``from . import y`` / ``from ..pkg import y``
    RELATIVE_IMPORT = "relative_import"
    #: ``importlib.import_module(...)`` / ``__import__(...)`` -- never resolvable, but
    #: recorded rather than dropped, per constraint C4.
    DYNAMIC = "dynamic"


def enum_column(enum_cls: type[StrEnum], name: str, length: int = 32) -> SAEnum:
    """Build the storage type for an enum column.

    ``native_enum=False`` stores VARCHAR; ``create_constraint=True`` adds the CHECK that
    makes the column genuinely constrained rather than merely conventionally so -- the
    default in SQLAlchemy 2.x is ``False``, which would leave any string acceptable.
    ``values_callable`` stores the member *value* (``"pending"``) rather than the member
    *name* (``"PENDING"``), so what lands in the database matches the API contract.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda e: [member.value for member in e],
    )
