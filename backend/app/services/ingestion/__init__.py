"""Ingestion of target repositories.

The first point at which untrusted input reaches this system: a URL becomes a real
process on the host. Cloning cannot happen inside the analysis sandbox, which has no
network by design (ADR 0009), so the host does it under an explicit lockdown instead --
see ADR 0011 for where the C1 boundary sits and why reading bytes is not analysis.

Everything later phases mine from git history has to be extracted here, because the
clone is deleted when the scan ends.
"""

from __future__ import annotations

from app.services.ingestion.errors import (
    CloneFailedError,
    CloneTimeoutError,
    IngestionError,
    RepositoryTooLargeError,
    UnsafeRepositoryUrlError,
)

__all__ = [
    "CloneFailedError",
    "CloneTimeoutError",
    "IngestionError",
    "RepositoryTooLargeError",
    "UnsafeRepositoryUrlError",
]
