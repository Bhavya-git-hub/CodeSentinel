"""Blaming the lines a bug-fix changed.

The middle step of SZZ: given a commit that fixed a defect, find the commits that last
touched the lines it repaired. Those are the suspects.

This reads git objects and never executes the target's code, so it runs on the host under
ADR 0011, exactly like history mining.

The subtlety that makes or breaks the result is *which* lines to blame. A fix's diff has
two sides, and only one of them is evidence: the lines it **removed or replaced** existed
before the fix and are what the defect lived in. The lines it **added** are the repair
itself and did not exist until the fix, so blaming them would attribute the defect to the
fix's own parent regardless of where the bug actually came from. So the ranges are taken
from the ``-`` side of each hunk, and the blame runs against the fix's parent.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

#: `@@ -12,5 +12,7 @@` -- the `-` side is the parent's line range.
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")

#: Bound on how many lines of one file a single fix may contribute. A reformatting commit
#: mislabelled as a fix would otherwise blame the entire file and name every commit in its
#: history as defect-inducing.
MAX_BLAMED_LINES_PER_FILE = 400


def parse_deleted_ranges(diff: str) -> dict[str, list[tuple[int, int]]]:
    """Per file, the parent-side line ranges a diff removed or replaced.

    Hunks with a zero-length `-` side are pure additions: the fix added code without
    touching anything that existed, so there is nothing there to blame.
    """
    ranges: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            continue
        if line.startswith("+++ /dev/null"):
            # The fix deleted the file. Its history is still real, but there are no
            # surviving lines to blame at the parent, and the file is gone at HEAD.
            current = None
            continue
        if current is None:
            continue
        match = HUNK.match(line)
        if match:
            start = int(match.group(1))
            length = int(match.group(2)) if match.group(2) is not None else 1
            if length > 0:
                ranges.setdefault(current, []).append((start, start + length - 1))
    return ranges


def _run(repo: Path, args: list[str]) -> str | None:
    """Run git in the clone, returning None rather than raising on failure.

    A single unblamable file must not abort the pass: the commit is still labelled from
    whatever else it touched, and the shortfall surfaces as fewer suspects rather than as
    a crashed scan.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        logger.warning("blame.git_unavailable", error=str(exc))
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def changed_line_ranges(repo: Path, sha: str) -> dict[str, list[tuple[int, int]]]:
    """The parent-side ranges this commit removed or replaced.

    ``-U0`` so the hunks carry no context lines: context was not changed by the fix, and
    blaming it would widen every suspect set with code the fix merely happened to sit near.
    """
    diff = _run(repo, ["diff", "-U0", "--no-color", f"{sha}^", sha])
    if diff is None:
        # No parent (the root commit) or an unreadable diff. A root commit has nothing
        # before it to have introduced the defect.
        return {}
    return parse_deleted_ranges(diff)


def parse_blame_shas(porcelain: str) -> set[str]:
    """The commit SHAs named by `git blame --porcelain` output.

    The porcelain format opens each group with `<sha> <orig-line> <final-line> <count>`,
    which is the only line that starts with a 40-character hex string.
    """
    shas: set[str] = set()
    for line in porcelain.splitlines():
        head = line.split(" ", 1)[0]
        if len(head) == 40:
            try:
                int(head, 16)
            except ValueError:
                continue
            shas.add(head)
    return shas


def blame_suspects(repo: Path, fix_sha: str) -> set[str]:
    """Commits that last touched the lines this fix repaired.

    Blamed at the fix's **parent**: at the fix itself those lines are already the repair,
    and blame would name the fix as its own cause.
    """
    suspects: set[str] = set()

    for path, ranges in changed_line_ranges(repo, fix_sha).items():
        budget = MAX_BLAMED_LINES_PER_FILE
        for start, end in ranges:
            if budget <= 0:
                logger.info("blame.truncated", sha=fix_sha[:12], path=path)
                break
            end = min(end, start + budget - 1)
            budget -= end - start + 1
            out = _run(
                repo,
                ["blame", "--porcelain", "-L", f"{start},{end}", f"{fix_sha}^", "--", path],
            )
            if out:
                suspects.update(parse_blame_shas(out))

    suspects.discard(fix_sha)
    return suspects
