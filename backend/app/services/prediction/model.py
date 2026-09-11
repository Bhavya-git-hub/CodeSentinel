"""A baseline defect-risk model, and the conditions under which it refuses to produce one.

This is a transparent frequency model, not a learned one: for a commit of a given size,
the probability is the rate at which commits of that size were labelled defect-inducing in
this repository's own history. Nothing is fitted, so nothing can overfit, and the output
is explainable to the person it is shown to -- "3 of the 11 commits this size introduced a
defect later fixed" is a sentence a reviewer can check.

The part that matters more than the formula is when it declines. SZZ labels only the
commits it can reach: a repository whose messages never say "fix" yields almost no
positives, and a frequency computed over four labelled commits is noise wearing the
costume of a probability. Below the minimum, no Prediction rows are written at all --
because a defect probability is precisely the kind of number that gets believed, and an
unjustified 0.34 is worse than a blank (C4).
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

#: Bumped whenever the formula or the buckets change. A probability is uninterpretable
#: without knowing what produced it, so it is stored on every row (C5).
MODEL_VERSION = "frequency-baseline-1"

#: Below this many labelled commits the rate is noise. Chosen so each bucket can hold a
#: handful: with fewer, a single defect swings a bucket's probability by tens of points.
MIN_LABELLED_COMMITS = 30

#: A rate needs both outcomes. Found by running a real scan: when the blame pass is
#: truncated nothing can be ruled out, so every label is True, and a frequency over an
#: all-positive set is 1.0 for every commit in it -- a confident number meaning nothing.
MIN_PER_CLASS = 5

#: Lines-changed boundaries. Size is the one feature that is both available for every
#: commit and repeatedly found to correlate with defect proneness; using more features
#: without fitting them would be inventing weights.
SIZE_BUCKETS: tuple[tuple[str, int], ...] = (
    ("tiny", 10),
    ("small", 50),
    ("medium", 250),
    ("large", 1000),
    ("huge", 10**9),
)


@dataclass(frozen=True, slots=True)
class LabelledCommit:
    """One commit as the model sees it."""

    sha: str
    lines_changed: int | None
    is_defect_inducing: bool | None


@dataclass(frozen=True, slots=True)
class Prediction:
    """A probability and the evidence behind it."""

    sha: str
    probability: float
    bucket: str
    #: How many labelled commits shared this bucket. Shown so a thin bucket is visible.
    sample_size: int


def bucket_for(lines_changed: int | None) -> str | None:
    """The size bucket, or None when the size is unknown.

    A commit whose stats could not be computed -- an all-binary diff -- is not a tiny
    commit. It has no bucket and gets no prediction, rather than being scored as though
    it changed nothing.
    """
    if lines_changed is None:
        return None
    for name, ceiling in SIZE_BUCKETS:
        if lines_changed <= ceiling:
            return name
    return SIZE_BUCKETS[-1][0]


def predict(commits: list[LabelledCommit]) -> tuple[list[Prediction], str | None]:
    """Score every commit, or decline and say why.

    Returns (predictions, reason). A non-None reason means no predictions were produced
    and the scan should record that rather than presenting an empty list as a result.
    """
    labelled = [c for c in commits if c.is_defect_inducing is not None]

    if len(labelled) < MIN_LABELLED_COMMITS:
        return [], (
            f"Not enough labelled history to model defect risk: SZZ could label "
            f"{len(labelled)} commits and at least {MIN_LABELLED_COMMITS} are needed. "
            f"No probabilities were produced. This usually means the repository's commit "
            f"messages rarely describe fixes, not that its commits are safe."
        )

    positives = sum(1 for c in labelled if c.is_defect_inducing)
    negatives = len(labelled) - positives
    if positives < MIN_PER_CLASS or negatives < MIN_PER_CLASS:
        # A rate computed from one class is not a rate. All-positive gives every commit
        # 1.0; all-negative gives every commit 0.0. Both look like findings.
        return [], (
            f"Defect risk could not be modelled: the labelled history has "
            f"{positives} defect-inducing and {negatives} clean commits, and at least "
            f"{MIN_PER_CLASS} of each are needed. This usually means the blame pass was "
            f"truncated, so nothing could be ruled out -- not that every commit is risky."
        )

    totals: dict[str, int] = {}
    defects: dict[str, int] = {}
    for commit in labelled:
        bucket = bucket_for(commit.lines_changed)
        if bucket is None:
            continue
        totals[bucket] = totals.get(bucket, 0) + 1
        if commit.is_defect_inducing:
            defects[bucket] = defects.get(bucket, 0) + 1

    if not totals:
        return [], (
            "No labelled commit had a computable size, so there is nothing to model "
            "against. Commits whose diffs are entirely binary carry no line counts."
        )

    # A bucket nobody landed in falls back to the overall rate rather than to zero: an
    # unobserved size is unknown, and zero would assert that commits of that size are safe.
    overall = sum(defects.values()) / sum(totals.values())

    predictions: list[Prediction] = []
    for commit in commits:
        bucket = bucket_for(commit.lines_changed)
        if bucket is None:
            # Unknown size, no prediction. Not scored at the average, which would be a
            # number about a commit we could not measure.
            continue
        seen = totals.get(bucket, 0)
        rate = (defects.get(bucket, 0) / seen) if seen else overall
        predictions.append(
            Prediction(sha=commit.sha, probability=round(rate, 4), bucket=bucket, sample_size=seen)
        )

    logger.info(
        "prediction.scored",
        commits=len(predictions),
        labelled=len(labelled),
        overall_rate=round(overall, 4),
    )
    return predictions, None
