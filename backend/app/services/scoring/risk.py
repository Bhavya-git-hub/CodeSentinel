"""Turning complexity and churn into a review queue.

The product is the claim this project makes: complexity says how easy a file is to get
wrong, churn says how often anyone is in a position to. Either alone ranks badly --
complex code nobody touches is not where defects land, and a heavily-edited trivial file
is not worth a reviewer's morning.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RiskInputs:
    """What is known about one file before scoring.

    Every field is optional because every one of them can genuinely fail to be
    determined, and each absence means something different downstream.
    """

    complexity: float | None
    churn: float | None
    maintainability: float | None = None


@dataclass(frozen=True, slots=True)
class RiskScore:
    """A file's score and the two components that produced it.

    The components are kept rather than discarded because a rank nobody can explain is a
    rank nobody acts on: a reviewer asked to trust "0.83" needs to see whether it came
    from complexity, from churn, or from both.
    """

    normalized_complexity: float | None
    normalized_churn: float | None
    risk_score: float | None


def normalize(values: dict[str, float | None]) -> dict[str, float | None]:
    """Scale to [0, 1] by dividing by the maximum, preserving None.

    Division by the maximum rather than min-max scaling. Min-max maps the least-complex
    file to exactly 0, which then zeroes its risk product no matter how hard it churns,
    and it divides by zero when every file is identical. Dividing by the maximum degrades
    gracefully in both cases: a lone file, or a set of equal ones, all score 1.0.

    A None stays None. Treating it as a 0 would both fabricate a measurement and drag the
    scale, changing every other file's score because of a file we failed to measure.
    """
    known = [value for value in values.values() if value is not None]
    largest = max(known, default=0.0)

    if largest <= 0.0:
        # Either nothing was measurable, or everything genuinely measured zero. Both are
        # honestly represented by 0.0 for the measured files.
        return {path: (None if value is None else 0.0) for path, value in values.items()}

    return {path: (None if value is None else value / largest) for path, value in values.items()}


def score_files(inputs: dict[str, RiskInputs]) -> dict[str, RiskScore]:
    """Score every file, leaving unmeasurable ones explicitly unknown.

    ``risk_score`` is None whenever either component is. Zero would be a claim that the
    file is safe, which is the opposite of what an unparseable file warrants -- and the
    ``ix_file_metrics_scan_id_risk_score`` index is DESC NULLS LAST precisely so an
    unknown cannot outrank a measured high-risk file (C4).
    """
    complexity = normalize({path: item.complexity for path, item in inputs.items()})
    churn = normalize({path: item.churn for path, item in inputs.items()})

    scores: dict[str, RiskScore] = {}
    unknown = 0

    for path in inputs:
        normalized_complexity = complexity[path]
        normalized_churn = churn[path]
        if normalized_complexity is None or normalized_churn is None:
            risk: float | None = None
            unknown += 1
        else:
            risk = normalized_complexity * normalized_churn
        scores[path] = RiskScore(
            normalized_complexity=normalized_complexity,
            normalized_churn=normalized_churn,
            risk_score=risk,
        )

    if unknown:
        # Surfaced, not swallowed: a queue built from part of a repository must say so.
        logger.info("risk.unscored_files", count=unknown, total=len(inputs))
    return scores
