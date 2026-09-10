"""Outcome of a single sandboxed command."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SandboxOutcome(StrEnum):
    """How a sandboxed command ended.

    ``COMPLETED`` says the command ran to completion, not that it succeeded -- a linter
    exiting non-zero because it found issues is a completed run. Callers must inspect
    ``exit_code`` for tool semantics and this field for sandbox semantics; conflating the
    two is how "pylint found problems" gets misreported as "the analyser failed".
    """

    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    OUT_OF_MEMORY = "out_of_memory"


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """What a sandboxed command produced.

    ``exit_code`` is ``None`` when the container never exited on its own -- it was killed
    at the timeout or by the OOM killer. It is deliberately not coerced to a number:
    substituting ``-1`` or ``137`` would make "killed" indistinguishable from a command
    that genuinely returned that code (constraint C4).
    """

    outcome: SandboxOutcome
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    @property
    def timed_out(self) -> bool:
        return self.outcome is SandboxOutcome.TIMED_OUT

    @property
    def oom_killed(self) -> bool:
        return self.outcome is SandboxOutcome.OUT_OF_MEMORY

    @property
    def truncated(self) -> bool:
        """Whether any captured output was cut short by the byte cap."""
        return self.stdout_truncated or self.stderr_truncated

    def describe_failure(self) -> str | None:
        """A reason string for a non-completed run, or None if it completed.

        Analyser adapters record this against the scan so a partial report explains
        itself (constraint C3).
        """
        if self.outcome is SandboxOutcome.TIMED_OUT:
            return f"command exceeded the sandbox timeout after {self.duration_seconds:.1f}s"
        if self.outcome is SandboxOutcome.OUT_OF_MEMORY:
            return "container was killed by the out-of-memory killer"
        return None
