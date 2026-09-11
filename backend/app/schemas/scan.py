"""Request and response models for the scans API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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


class FileRisk(BaseModel):
    """One file's place in the review queue, with the components that put it there."""

    path: str
    is_test: bool
    loc: int | None
    cyclomatic_complexity: float | None
    maintainability_index: float | None
    churn_score: float | None
    normalized_complexity: float | None
    normalized_churn: float | None
    risk_score: float | None


class RiskQueue(BaseModel):
    """A scan's risk-ranked files.

    ``unmeasured`` is part of the contract, not a footnote. A queue built from half a
    repository has to say so, or a short list reads as a clean bill of health (C3).
    """

    scan_id: uuid.UUID
    status: ScanStatus
    total_files: int
    unmeasured: int
    analyzer_statuses: dict[str, Any]
    files: list[FileRisk]
