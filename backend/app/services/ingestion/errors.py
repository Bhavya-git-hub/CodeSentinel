"""Ingestion failures.

A target repository that is genuinely too large, or unreachable, is an ordinary
recordable outcome of the work -- not a fault in this system. These exceptions carry the
fact an operator needs to act on (the limit, the measured size, the timeout, the exit
status), because an error that only says "clone failed" costs someone a reproduction.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for failures to ingest a target repository."""


class UnsafeRepositoryUrlError(IngestionError):
    """The URL was refused before any process was started.

    Refused rather than sanitised: an ext:: URL is arbitrary command execution on the
    host, and quietly rewriting a caller's URL into a different one is a surprising side
    effect that hides the attempt.
    """


class RepositoryTooLargeError(IngestionError):
    """The clone exceeded the configured size budget and was abandoned.

    The partial tree is deleted. This protects the host, so it is enforced during the
    clone rather than checked afterwards -- by which point the disk is already full.
    """


class CloneTimeoutError(IngestionError):
    """The clone exceeded its time budget and the process was killed.

    Killed rather than abandoned: a wait that merely stops waiting leaves git running
    and still filling the disk (the lesson ADR 0010 records for containers).
    """


class CloneFailedError(IngestionError):
    """git exited non-zero. The message carries the exit status and stderr summary."""
