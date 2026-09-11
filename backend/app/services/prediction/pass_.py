"""The SZZ pass: label the history, then score it.

Runs while the clone still exists, because blame needs the repository on disk and the
scan deletes it when it finishes.

The whole pass is built so that a commit it could not judge stays NULL. That is not
defensive coding, it is the product requirement: ``is_bugfix`` and
``is_defect_inducing`` are tri-state (ADR 0004), and a False written where the truth is
"we did not look" becomes a negative training example for a defect that exists. Phase 1
made these columns nullable for exactly this moment.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.history import Commit, Prediction
from app.services.prediction import model as risk_model
from app.services.prediction.blame import blame_suspects
from app.services.prediction.szz import CandidateCommit, label_bugfixes

logger = structlog.get_logger(__name__)

ANALYZER_NAME = "szz"

#: Blaming every fix in a long history is the slowest thing a scan does, and the marginal
#: value of the thousandth fix is small. Bounded, and the bound is reported so a truncated
#: pass is visible rather than silently partial.
MAX_FIXES_BLAMED = 300


async def run_szz(
    session: AsyncSession,
    *,
    scan_id: uuid.UUID,
    repository_id: uuid.UUID,
    clone_path: Path,
) -> str | None:
    """Label commits and write predictions. Returns a reason if incomplete.

    A reason rather than an exception: a repository whose messages never mention fixes is
    an ordinary thing to encounter, and the rest of the scan is still valid.
    """
    commits = (
        (
            await session.execute(
                select(
                    Commit.id,
                    Commit.sha,
                    Commit.message_summary,
                    Commit.authored_at,
                    Commit.lines_added,
                    Commit.lines_deleted,
                ).where(Commit.repository_id == repository_id)
            )
        )
        .tuples()
        .all()
    )

    if not commits:
        return "No commits were mined, so there was no history to label."

    candidates = [
        CandidateCommit(sha=sha, summary=summary, authored_at=authored_at)
        for _id, sha, summary, authored_at, _a, _d in commits
    ]
    bugfix_shas, undecided_shas = label_bugfixes(candidates)
    dates = {c.sha: c.authored_at for c in candidates}

    # --- blame each fix -----------------------------------------------------
    inducing: set[str] = set()
    ordered_fixes = sorted(bugfix_shas)
    truncated = len(ordered_fixes) > MAX_FIXES_BLAMED

    for sha in ordered_fixes[:MAX_FIXES_BLAMED]:
        for suspect in blame_suspects(clone_path, sha):
            # Only commits we actually mined, and only ones older than the fix. A suspect
            # we know nothing about cannot be labelled, and one newer than the fix cannot
            # have caused it -- rewritten history makes both reachable.
            suspect_date = dates.get(suspect)
            if suspect_date is not None and suspect_date < dates[sha]:
                inducing.add(suspect)

    # --- write the labels ---------------------------------------------------
    # Decided negatives only. A commit in undecided_shas had no message to judge, and a
    # suspect set built from a truncated blame pass cannot rule anything out either.
    can_rule_out = not truncated
    labelled_negative = 0

    for commit_id, sha, _summary, _authored, _a, _d in commits:
        row = await session.get(Commit, commit_id)
        if row is None:
            continue
        if sha in undecided_shas:
            row.is_bugfix = None
        else:
            row.is_bugfix = sha in bugfix_shas
        if sha in inducing:
            row.is_defect_inducing = True
        elif can_rule_out and sha not in undecided_shas:
            row.is_defect_inducing = False
            labelled_negative += 1
        else:
            row.is_defect_inducing = None
    await session.commit()

    # --- score --------------------------------------------------------------
    labelled = [
        risk_model.LabelledCommit(
            sha=sha,
            lines_changed=(
                None if added is None and deleted is None else (added or 0) + (deleted or 0)
            ),
            is_defect_inducing=(
                True
                if sha in inducing
                else (False if can_rule_out and sha not in undecided_shas else None)
            ),
        )
        for _id, sha, _summary, _authored, added, deleted in commits
    ]
    predictions, decline = risk_model.predict(labelled)

    if predictions:
        session.add_all(
            [
                Prediction(
                    scan_id=scan_id,
                    commit_sha=p.sha,
                    defect_probability=p.probability,
                    model_version=risk_model.MODEL_VERSION,
                )
                for p in predictions
            ]
        )
        await session.commit()

    logger.info(
        "szz.done",
        scan_id=str(scan_id),
        commits=len(commits),
        bugfixes=len(bugfix_shas),
        undecided=len(undecided_shas),
        defect_inducing=len(inducing),
        negatives=labelled_negative,
        predictions=len(predictions),
    )

    reasons: list[str] = []
    if truncated:
        reasons.append(
            f"Only the first {MAX_FIXES_BLAMED} of {len(bugfix_shas)} bug-fix commits were "
            f"blamed, so commits not named as defect-inducing are recorded as unknown "
            f"rather than as clean."
        )
    if undecided_shas:
        reasons.append(
            f"{len(undecided_shas)} commits had no message to classify and are left unlabelled."
        )
    if decline:
        reasons.append(decline)
    return " ".join(reasons) if reasons else None
