"""Mining a cloned repository's commit history.

This is the data that distinguishes CodeSentinel from a linter, and it exists only while
the clone does -- the scan deletes the working tree when it finishes. Anything phases 4
and 8 need has to be extracted in this one pass.

Merge commits are excluded. A merge's diffstat re-counts changes already attributed to
its parents, so including them would inflate churn on every file touched by a merged
branch, in proportion to how often the project merges rather than how often the file
changed.

Output is streamed rather than accumulated: a mature repository carries six figures of
commits, and holding them all in memory to insert them at the end trades a bounded walk
for an unbounded one. That constrains the implementation -- ``subprocess.run`` reads the
whole of stdout before returning a single byte, so this drives a ``Popen`` and consumes
its output line by line instead.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import structlog

from app.models.enums import ChangeType

logger = structlog.get_logger(__name__)

#: Delimits commit headers in `git log` output. Chosen because it cannot occur in a SHA,
#: an email, an ISO timestamp or a subject line.
RECORD_SEPARATOR = "\x1e"
FIELD_SEPARATOR = "\x1f"

_RENAME_BRACE = re.compile(r"^(?P<prefix>.*)\{(?P<old>[^}]*) => (?P<new>[^}]*)\}(?P<suffix>.*)$")


class HistoryMiningError(Exception):
    """``git log`` failed or produced output that could not be read.

    Not an :class:`~app.services.ingestion.errors.IngestionError`: a clone that cannot be
    mined still yielded a usable file inventory, and the pipeline records that outcome as
    PARTIAL rather than FAILED. Sharing the base class would invite a caller to treat the
    two as the same thing.
    """


@dataclass(frozen=True, slots=True)
class FileChangeRecord:
    """One file touched by one commit."""

    path: str
    lines_added: int | None
    lines_deleted: int | None
    change_type: ChangeType


@dataclass(frozen=True, slots=True)
class CommitRecord:
    """One non-merge commit.

    Every count is optional. git omits a diffstat for some commits, and reports '-' for
    binary files; a 0 in either case would be a number we invented.
    """

    sha: str
    author_email: str | None
    authored_at: datetime
    message_summary: str | None
    files_changed: int | None
    lines_added: int | None
    lines_deleted: int | None
    changes: list[FileChangeRecord] = field(default_factory=list)


def _resolve_rename(path: str) -> tuple[str, bool]:
    """Turn git's rename notation into the destination path.

    git writes ``pkg/{old.py => new.py}`` or ``old.py => new.py``. Churn is attributed to
    where the file is now, because that is the row phase 4 will rank.
    """
    match = _RENAME_BRACE.match(path)
    if match:
        rebuilt = f"{match['prefix']}{match['new']}{match['suffix']}"
        return rebuilt.replace("//", "/"), True
    if " => " in path:
        return path.split(" => ", 1)[1], True
    return path, False


def parse_numstat_line(line: str) -> FileChangeRecord | None:
    """One `--numstat` line into a record, or None if the line is not one."""
    if not line.strip():
        return None

    parts = line.split("\t")
    if len(parts) < 3:
        return None

    raw_added, raw_deleted, raw_path = parts[0], parts[1], "\t".join(parts[2:])

    # '-' is git's marker for a binary diff: the change is real but uncountable.
    try:
        added = None if raw_added.strip() == "-" else int(raw_added)
        deleted = None if raw_deleted.strip() == "-" else int(raw_deleted)
    except ValueError:
        # Not a numstat line at all. Reported rather than guessed at, so a git output
        # change shows up as a log event instead of as silently missing churn.
        logger.warning("history.unparsable_numstat", line=line[:120])
        return None

    path, renamed = _resolve_rename(raw_path.strip())

    if renamed:
        change_type = ChangeType.RENAMED
    elif added is not None and deleted == 0 and added > 0:
        change_type = ChangeType.ADDED
    elif deleted is not None and added == 0 and deleted > 0:
        change_type = ChangeType.DELETED
    else:
        change_type = ChangeType.MODIFIED

    return FileChangeRecord(
        path=path, lines_added=added, lines_deleted=deleted, change_type=change_type
    )


def mine_history(repo_path: Path) -> Iterator[CommitRecord]:
    """Stream non-merge commits, newest first, with their per-file changes.

    A generator on purpose. The caller persists in batches, so the memory ceiling is the
    batch rather than the repository -- which matters because the targets worth scanning
    are exactly the ones with long histories.
    """
    log_format = FIELD_SEPARATOR.join(["%H", "%aE", "%aI", "%s"])
    command = [
        "git",
        "log",
        "--no-merges",
        "--numstat",
        f"--format={RECORD_SEPARATOR}{log_format}",
        "--date=iso-strict",
    ]

    # stderr goes to a temporary file rather than a pipe. A pipe nobody drains while
    # stdout is still being read is a deadlock waiting for an unusually chatty repository;
    # a file cannot fill up in that way.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errors:
        process = subprocess.Popen(
            command,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            if process.stdout is None:  # pragma: no cover - Popen always gives us one
                raise HistoryMiningError("git log produced no output stream")
            yield from _stream_records(process.stdout)
        finally:
            # The consumer may abandon this generator part-way through a large history.
            # git would otherwise keep walking and writing into a pipe nobody reads.
            if process.poll() is None:
                process.terminate()
            process.wait()

        if process.returncode != 0:
            errors.seek(0)
            detail = errors.read().strip()
            raise HistoryMiningError(
                f"git log exited {process.returncode}: {detail[:500] or 'no stderr output'}"
            )


def _stream_records(stdout: Iterator[str]) -> Iterator[CommitRecord]:
    """Split the log stream on record boundaries without buffering all of it.

    Each commit's header line begins with RECORD_SEPARATOR, so a new header is the signal
    that the previous commit's numstat block is complete.
    """
    block: list[str] = []

    for line in stdout:
        if line.startswith(RECORD_SEPARATOR):
            if block:
                record = _parse_block("".join(block))
                if record is not None:
                    yield record
            block = [line[len(RECORD_SEPARATOR) :]]
        elif block:
            block.append(line)

    if block:
        record = _parse_block("".join(block))
        if record is not None:
            yield record


def _parse_block(block: str) -> CommitRecord | None:
    """One commit's header plus its numstat lines."""
    header, _, body = block.partition("\n")
    fields = header.split(FIELD_SEPARATOR)
    if len(fields) < 4:
        logger.warning("history.malformed_header", header=header[:120])
        return None

    sha, author_email, authored_raw, summary = fields[0], fields[1], fields[2], fields[3]

    try:
        authored_at = datetime.fromisoformat(authored_raw)
    except ValueError:
        logger.warning("history.unparsable_date", sha=sha, value=authored_raw)
        return None

    changes = [
        change for change in (parse_numstat_line(line) for line in body.splitlines()) if change
    ]

    countable = [c for c in changes if c.lines_added is not None and c.lines_deleted is not None]

    return CommitRecord(
        sha=sha,
        author_email=author_email or None,
        authored_at=authored_at,
        message_summary=summary or None,
        files_changed=len(changes) or None,
        # Sum only what was countable. If every change was binary there is nothing to
        # sum, and reporting 0 would claim the commit changed no lines.
        lines_added=sum(c.lines_added or 0 for c in countable) if countable else None,
        lines_deleted=sum(c.lines_deleted or 0 for c in countable) if countable else None,
        changes=changes,
    )
