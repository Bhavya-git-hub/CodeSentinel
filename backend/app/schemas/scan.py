"""Request and response models for the scans API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ScanStatus, Severity


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
    #: Null means coverage was not measured for this file, not that it is untested.
    coverage_pct: float | None


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


class FindingItem(BaseModel):
    """One issue, on the single normalised severity scale.

    ``path`` is null for a finding the analyser could not attribute to a file in the
    inventory. Those are kept rather than dropped, so the count is honest (C4).
    """

    analyzer: str
    rule_id: str
    severity: Severity
    message: str
    path: str | None
    line_start: int | None
    line_end: int | None


class FindingsPage(BaseModel):
    """A scan's findings, with the analyser outcomes that produced them.

    ``analyzer_statuses`` travels with the list because an empty list from an analyser
    that ran and an empty list from one that never ran are different facts, and only the
    statuses tell them apart (C3).
    """

    scan_id: uuid.UUID
    status: ScanStatus
    total: int
    by_severity: dict[str, int]
    analyzer_statuses: dict[str, Any]
    findings: list[FindingItem]


class ImpactedFile(BaseModel):
    """A file that transitively imports the one being changed."""

    path: str
    #: Import hops away. 1 means it imports the changed file directly.
    distance: int
    risk_score: float | None


class BlastRadius(BaseModel):
    """What breaks if one file changes.

    ``unresolved_edges`` is part of the answer, not a diagnostic. Edges the graph could
    not follow -- third-party imports, dynamic imports, relative imports above the root --
    mean the true radius is at least this large and possibly larger. A reviewer told only
    the resolved count would read a floor as a ceiling (C4).
    """

    scan_id: uuid.UUID
    path: str
    depth: int
    impacted: list[ImpactedFile]
    resolved_edges: int
    unresolved_edges: int


class CommitRisk(BaseModel):
    """One commit's modelled defect probability, with the evidence behind it.

    ``model_version`` travels with the number because a probability is uninterpretable
    without knowing what produced it (C5).
    """

    commit_sha: str
    defect_probability: float
    model_version: str


class Limitation(BaseModel):
    """One thing this scan could not determine, and what it means for the reader.

    The report carries these as first-class content rather than a footnote. A report that
    lists only what it found reads as complete, and the reader has no way to tell the
    difference between "clean" and "not looked at" (C3).
    """

    subject: str
    detail: str
    consequence: str


class ScanReport(BaseModel):
    """Everything one scan produced, with its own limits stated alongside."""

    scan_id: uuid.UUID
    status: ScanStatus
    commit_sha: str | None
    started_at: datetime
    completed_at: datetime | None

    file_count: int
    commit_count: int
    files_ranked: int
    files_unmeasured: int

    findings_total: int
    findings_by_severity: dict[str, int]

    dependency_edges: int
    dependency_edges_unresolved: int

    coverage_measured_files: int

    top_risks: list[FileRisk]
    #: How many commits SZZ could label, and how many it blamed for a later fix.
    commits_labelled: int
    commits_defect_inducing: int
    top_defect_risks: list[CommitRisk]
    limitations: list[Limitation]
    #: Settings in force when the scan was dispatched (C5).
    config: dict[str, Any]
    analyzer_statuses: dict[str, Any]
