"""Cloning a target repository onto the host, under lockdown.

Cloning cannot happen inside the analysis sandbox: that container has no network by
design and there is no argument that gives it one (ADR 0009). So the clone runs on the
host, which means git runs against a hostile URL, and the hardening below is the whole
defence. See ADR 0011 for why reading a repository's bytes is not the "analysis" C1
confines to the sandbox.

The obvious implementation -- Repo.clone_from with a RemoteProgress subclass that raises
once the destination is too big -- does not work. GitPython dispatches progress from
daemon pump threads that catch handler exceptions and re-raise them into the dying pump
thread, never into the caller. git keeps running and keeps filling the disk while a
pytest.raises test passes. So this module drives the process itself and owns the Popen.

Driving the process directly bypasses clone_from's check_unsafe_protocols screen, which
is why validate_repository_url runs first and why protocol.allow=never is set explicitly.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from git import Git

from app.config import Settings
from app.services.ingestion.errors import (
    CloneFailedError,
    CloneTimeoutError,
    RepositoryTooLargeError,
)
from app.services.ingestion.url import validate_repository_url

logger = structlog.get_logger(__name__)

BYTES_PER_MB = 1024 * 1024
#: Grace period between asking the clone to stop and killing it outright.
TERMINATE_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class CloneResult:
    """A successful clone.

    ``default_branch`` is optional because a repository with a detached or unresolvable
    HEAD has no branch name to record, and inventing one would be fabricated data (C4).
    """

    path: Path
    commit_sha: str
    default_branch: str | None


def directory_size_bytes(path: Path) -> int:
    """Total size of every regular file under ``path``.

    Symlinks are counted but never followed: a target can point one at / and a following
    walk would measure the whole host filesystem.
    """
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            candidate = Path(root) / name
            try:
                info = candidate.lstat()
            except OSError:
                # A file git removed mid-walk is not an error; it simply no longer
                # contributes to the size.
                continue
            if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                total += info.st_size
    return total


def build_clone_command(url: str, destination: Path, *, settings: Settings) -> list[str]:
    """The exact argv for the clone.

    Built as a separate function so the isolation can be asserted without a network: a
    unit test can prove what was requested, which is the half of the guarantee that runs
    everywhere.
    """
    config: list[str] = [
        # Deny every transport, then re-enable exactly the allowlisted ones. Ordering
        # matters: the blanket denial has to come first.
        "-c",
        "protocol.allow=never",
    ]
    for protocol in settings.clone_allowed_protocols:
        config += ["-c", f"protocol.{protocol.lower()}.allow=always"]

    config += [
        # Hooks in a cloned repository must never run. core.hooksPath pointed at a
        # non-existent path is how git is told there are none.
        "-c",
        "core.hooksPath=/nonexistent",
        # A symlink in the target could otherwise point outside the clone root.
        "-c",
        "core.symlinks=false",
        # Never consult or write the host user's credentials.
        "-c",
        "credential.helper=",
    ]

    return [
        "git",
        *config,
        "clone",
        "--no-recurse-submodules",
        # No --depth: phase 4 churn and phase 8 SZZ need the complete commit graph. The
        # size guard replaces the bound a shallow clone would have given.
        "--quiet",
        "--",
        url,
        str(destination),
    ]


def _clone_environment() -> dict[str, str]:
    """Environment for the clone process.

    Prompts are disabled rather than answered: a clone that waits for a password holds a
    worker slot until the timeout, which is a denial of service with extra steps.
    """
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        # Never read the host user's git configuration: a global insteadOf rule could
        # rewrite the URL we validated into one we did not.
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }


def clone_repository(url: str, destination: Path, *, settings: Settings) -> CloneResult:
    """Clone ``url`` into ``destination``, bounded in size and time.

    Raises rather than returning a partial result: every caller of this needs a usable
    working tree, and a half-cloned repository analysed as if complete would produce a
    confident report about code nobody has.
    """
    safe_url = validate_repository_url(url, settings=settings)
    limit_bytes = settings.max_repo_size_mb * BYTES_PER_MB
    command = build_clone_command(safe_url, destination, settings=settings)

    logger.info("clone.start", url=safe_url, limit_mb=settings.max_repo_size_mb)
    # argv is a list and shell=False, so nothing in the URL can be shell-interpreted.
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clone_environment(),
        text=True,
    )

    try:
        _supervise(process, destination, limit_bytes=limit_bytes, settings=settings)
    except BaseException:
        remove_tree(destination)
        raise

    # An exact measurement after the fact: the sampling loop bounds growth during the
    # clone, but only this says what actually landed.
    measured = directory_size_bytes(destination)
    if measured > limit_bytes:
        removed = remove_tree(destination)
        aftermath = (
            "The partial clone was removed."
            if removed
            else f"The partial clone at {destination} could NOT be removed and is still on disk."
        )
        raise RepositoryTooLargeError(
            f"The repository is {measured // BYTES_PER_MB} MB, which exceeds the "
            f"{settings.max_repo_size_mb} MB limit. {aftermath}"
        )

    make_world_readable(destination)
    commit_sha, default_branch = _resolve_head(destination)
    logger.info(
        "clone.done",
        sha=commit_sha,
        branch=default_branch,
        size_mb=measured // BYTES_PER_MB,
    )
    return CloneResult(path=destination, commit_sha=commit_sha, default_branch=default_branch)


def _supervise(
    process: subprocess.Popen[str],
    destination: Path,
    *,
    limit_bytes: int,
    settings: Settings,
) -> None:
    """Watch the clone, killing it if it outgrows or outlasts its budget."""
    deadline = time.monotonic() + settings.clone_timeout_seconds
    interval = settings.clone_size_check_interval_seconds

    while True:
        try:
            process.wait(timeout=interval)
            break
        except subprocess.TimeoutExpired:
            pass

        if directory_size_bytes(destination) > limit_bytes:
            _kill(process)
            raise RepositoryTooLargeError(
                f"The repository exceeded the {settings.max_repo_size_mb} MB limit while "
                f"cloning and was abandoned."
            )

        if time.monotonic() > deadline:
            _kill(process)
            raise CloneTimeoutError(
                f"The clone exceeded its {settings.clone_timeout_seconds}s budget and was killed."
            )

    if process.returncode != 0:
        stderr = (process.stderr.read() if process.stderr else "").strip()
        raise CloneFailedError(
            f"git clone exited {process.returncode}: {stderr[:500] or 'no stderr output'}"
        )


def _kill(process: subprocess.Popen[str]) -> None:
    """Stop the clone and wait for it to actually be gone.

    Terminate first, then kill: git left running would keep writing to a directory we are
    about to delete. Waiting is the point -- a kill that is not waited on is the same
    abandonment ADR 0010 rejects for containers.
    """
    process.terminate()
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def make_world_readable(path: Path) -> None:
    """Make the tree readable by the sandbox uid.

    Phase 2 recorded this as an obligation on ingestion. The analysis container runs as
    uid 10001, which never matches the host user that made the clone, so a tree that is
    not world-readable is invisible inside it: every analyser sees an empty workspace,
    finds nothing, and the scan looks healthy. A clean report for a repository nobody
    analysed is the worst output this system can produce.

    POSIX-only. Windows mode bits do not describe container access, and the sandbox does
    not run there.
    """
    if os.name != "posix":
        return
    for root, dirs, files in os.walk(path):
        Path(root).chmod(Path(root).stat().st_mode | 0o755)
        for name in dirs:
            target = Path(root) / name
            target.chmod(target.stat().st_mode | 0o755)
        for name in files:
            target = Path(root) / name
            target.chmod(target.stat().st_mode | 0o644)


def _resolve_head(destination: Path) -> tuple[str, str | None]:
    """The cloned commit SHA, and the branch name if there is one."""
    git = Git(str(destination))
    commit_sha = str(git.rev_parse("HEAD"))
    try:
        branch = str(git.rev_parse("--abbrev-ref", "HEAD"))
    except Exception as exc:  # noqa: BLE001 - reported as an absent branch, below
        logger.warning("clone.branch_unresolved", error=str(exc))
        return commit_sha, None
    return commit_sha, None if branch == "HEAD" else branch


def _force_writable(function: Any, path: str, _excinfo: Any) -> None:
    """rmtree error handler: clear the read-only bit and retry once.

    git writes its loose objects and pack files mode 0444, because their content is
    immutable. That makes a partial clone undeletable by a naive rmtree on Windows,
    where unlink requires the *file* to be writable -- POSIX only requires the parent
    directory to be, which is why this failure cannot reproduce in CI.

    Both the entry and its parent are made writable: the POSIX case fails on the
    directory, the Windows case on the file, and a handler that fixed only one would
    leave the other platform broken while looking correct on the one it was written on.
    """
    target = Path(path)
    for candidate in (target.parent, target):
        try:
            candidate.chmod(candidate.stat().st_mode | stat.S_IWUSR)
        except OSError:
            # Nothing recoverable here; the retry below reports the real failure.
            continue
    function(path)


def remove_tree(path: Path) -> bool:
    """Delete a partial clone, reporting whether it is actually gone.

    Returns a bool rather than swallowing failure. ``ignore_errors=True`` was the
    obvious spelling and it is the wrong one: it turns an undeletable tree into a silent
    success, so the caller goes on to raise "the partial clone was removed" about a tree
    still sitting on the disk the size guard exists to protect. The sandbox already
    refuses to swallow a container it could not remove (``runner.py``); an abandoned
    clone is the same leak and gets the same treatment.

    Never raises: every call site is already on a failure path and must not lose the
    original error to a cleanup problem.
    """
    if not path.exists():
        return True
    try:
        shutil.rmtree(path, onerror=_force_writable)
    except OSError as exc:
        # Reported, never swallowed: an undeletable clone is disk the host does not get
        # back, and the operator needs the path to clear it by hand.
        logger.error("clone.cleanup_failed", path=str(path), error=str(exc))
        return False
    return True
