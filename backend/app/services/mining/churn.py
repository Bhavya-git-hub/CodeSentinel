"""Recency-weighted churn.

Computed from rows this system already recorded, never from the target, so nothing a
repository contains can influence it beyond the line counts phase 3 mined. That is why it
runs on the host while complexity runs in the sandbox.

Total lifetime churn is the obvious metric and it is the wrong one: it ranks a file
rewritten five years ago above one being actively churned this month, which is exactly
backwards for "what should I review". Weighting by recency is the entire value of the
measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChangeWeight:
    """One change to one file, as churn needs to see it.

    Both counts are optional because git reports ``-`` for a binary diff: the change
    happened, its size is unknown.
    """

    changed_at: datetime
    lines_added: int | None
    lines_deleted: int | None

    @property
    def magnitude(self) -> int | None:
        """Lines touched, or None when nothing about this change was countable."""
        if self.lines_added is None and self.lines_deleted is None:
            return None
        return (self.lines_added or 0) + (self.lines_deleted or 0)


def churn_score(
    changes: list[ChangeWeight], *, as_of: datetime, half_life_days: float
) -> float | None:
    """Exponentially decayed churn, or None when it could not be determined.

    ``as_of`` is the scan's own start time rather than "now", so re-reading a stored scan
    yields the number it yielded when it ran (C5). A score that drifts every time it is
    read is not reproducible and cannot be compared between scans.

    The return value carries three distinct facts and they must not be conflated:

    - ``0.0`` -- the file has no changes in the mined history. A real measurement.
    - a positive float -- the decayed sum of what was countable.
    - ``None`` -- the file demonstrably changed, but every change was binary, so the
      magnitude is unknown. Reporting 0 here would rank an actively-churning binary-heavy
      file as never-touched and sink it to the bottom of the queue it belongs near the top
      of (anti-pattern #2).
    """
    if not changes:
        return 0.0

    total = 0.0
    counted = 0

    for change in changes:
        magnitude = change.magnitude
        if magnitude is None:
            continue
        # max(0, ...) because committer clocks lie and a timestamp in the future would
        # otherwise produce a weight above 1, letting a wrong clock outrank real recency.
        age_days = max(0.0, (as_of - change.changed_at).total_seconds() / 86_400)
        total += magnitude * 0.5 ** (age_days / half_life_days)
        counted += 1

    if counted == 0:
        return None
    return total
