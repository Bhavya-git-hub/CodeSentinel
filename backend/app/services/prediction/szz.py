"""Simplified SZZ: which commits introduced the defects this repository later fixed.

The method is: find commits that fix bugs, look at the lines they changed, blame those
lines to the commits that last touched them, and label those commits defect-inducing.

Every step of that is an inference, and the failure mode of the whole technique is
confidently labelling commits it guessed at. Two rules keep it honest.

**Unlabelled is not negative.** ``is_bugfix`` and ``is_defect_inducing`` are tri-state.
NULL means the pass has not run, or ran and could not decide. Defaulting an undecided
commit to False would inject fabricated negative examples into the training set, and a
model trained on invented labels is worse than no model, because it is confident (C4).
This is why phase 1 made those columns nullable, and the reason survives here.

**The bug-fix vocabulary is conservative on purpose.** Matching "fix" as a substring
catches "prefix", "suffix", "fixture" and "fixed formatting". Every false positive
propagates: it blames whichever commits last touched those lines, and they become
defect-inducing training examples for changes that fixed nothing. So the patterns require
word boundaries and lean towards missing real fixes rather than inventing them -- and the
recall cost is recorded rather than hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import structlog

logger = structlog.get_logger(__name__)

#: Word-boundary patterns. Deliberately narrow: a false positive here becomes a
#: fabricated training label, which is more expensive than a missed fix.
BUGFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfix(?:e[sd])?\b", re.IGNORECASE),
    re.compile(r"\bbugs?\b", re.IGNORECASE),
    re.compile(r"\bdefects?\b", re.IGNORECASE),
    re.compile(r"\bregressions?\b", re.IGNORECASE),
    re.compile(r"\bcrash(?:e[sd])?\b", re.IGNORECASE),
    re.compile(r"\bhotfix\b", re.IGNORECASE),
    re.compile(r"\bresolve[sd]?\s+#\d+\b", re.IGNORECASE),
    re.compile(r"\bcloses?\s+#\d+\b", re.IGNORECASE),
)

#: Phrases that look like fixes and are not. Checked first, because "fix typo" matches
#: the bug-fix pattern while fixing no defect the model should learn from.
NOT_A_BUGFIX: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bfix(?:e[sd])?\s+(?:typo|spelling|formatting|lint|whitespace|indent)", re.IGNORECASE
    ),
    re.compile(
        r"\bfix(?:e[sd])?\s+(?:the\s+)?(?:docs?|documentation|comment|readme)\b", re.IGNORECASE
    ),
    re.compile(r"\bmerge\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class BugfixVerdict:
    """Whether a message describes a bug fix, and why we think so.

    ``matched`` is None when the message is empty -- undecidable rather than negative.
    """

    matched: bool | None
    reason: str


def classify_message(summary: str | None) -> BugfixVerdict:
    """Whether this commit message describes fixing a defect.

    Returns None for an absent message. A commit with no summary is one we cannot judge,
    and recording it as "not a bug fix" would be a claim we have no basis for.
    """
    if summary is None or not summary.strip():
        return BugfixVerdict(None, "the commit has no message to classify")

    for pattern in NOT_A_BUGFIX:
        if pattern.search(summary):
            return BugfixVerdict(
                False, f"matched an exclusion ({pattern.pattern.split(chr(92))[0] or 'phrase'})"
            )

    for pattern in BUGFIX_PATTERNS:
        if pattern.search(summary):
            return BugfixVerdict(True, "matched a bug-fix indicator")

    return BugfixVerdict(False, "no bug-fix indicator in the message")


@dataclass(frozen=True, slots=True)
class BlameLine:
    """One line of a file, attributed to the commit that last changed it."""

    path: str
    line_number: int
    commit_sha: str


@dataclass(frozen=True, slots=True)
class SzzResult:
    """The labels one SZZ pass produced, and what it could not decide.

    ``undecided`` is reported rather than folded into the negatives. A pass that could
    classify 40 of 900 commits and says so is useful; one that reports 860 negatives is
    actively misleading.
    """

    bugfix_shas: set[str]
    defect_inducing_shas: set[str]
    undecided_shas: set[str]
    #: Why the pass is incomplete, when it is. None means it ran end to end.
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateCommit:
    """A commit as SZZ needs to see it."""

    sha: str
    summary: str | None
    authored_at: datetime


def label_bugfixes(commits: list[CandidateCommit]) -> tuple[set[str], set[str]]:
    """Split commits into bug fixes and ones we could not classify.

    Returns (bugfix shas, undecided shas). Everything not in either set is a decided
    negative, and the caller must keep that distinction: only decided negatives may be
    written as False.
    """
    bugfixes: set[str] = set()
    undecided: set[str] = set()
    for commit in commits:
        verdict = classify_message(commit.summary)
        if verdict.matched is None:
            undecided.add(commit.sha)
        elif verdict.matched:
            bugfixes.add(commit.sha)
    return bugfixes, undecided


def induce_from_blame(
    blame: list[BlameLine],
    *,
    fix_authored_at: datetime,
    commit_dates: dict[str, datetime],
) -> set[str]:
    """Commits blamed for lines a bug fix changed.

    A commit is only a suspect if it predates the fix. Blame can attribute a line to a
    commit later than the fix when history has been rewritten or a merge reorders dates,
    and labelling a later commit as having induced an earlier fix is a causality error
    that would quietly corrupt the training set.

    A blamed sha with no known date is skipped rather than assumed older. Assuming would
    be inventing the ordering the check exists to verify.
    """
    suspects: set[str] = set()
    for line in blame:
        authored = commit_dates.get(line.commit_sha)
        if authored is None:
            continue
        if authored < fix_authored_at:
            suspects.add(line.commit_sha)
    return suspects
