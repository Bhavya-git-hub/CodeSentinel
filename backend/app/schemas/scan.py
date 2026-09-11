"""Request and response models for the scans API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ScanStatus


class ScanRequest(BaseModel):
    """A request to analyse a public repository."""

    url: str = Field(min_length=1, max_length=2048)


class ScanAccepted(BaseModel):
    """The response to a dispatched scan. Deliberately minimal: the scan has not run."""

    scan_id: uuid.UUID
    status: ScanStatus


class ScanDetail(BaseModel):
    """A scan's current state.

    ``error`` is populated for a FAILED scan and says why in terms the caller can act on.
    ``commit_sha`` is null until the clone resolves the ref.
    """

    scan_id: uuid.UUID
    status: ScanStatus
    commit_sha: str | None
    error: str | None
    file_count: int
    commit_count: int
    started_at: datetime
    completed_at: datetime | None
