"""Pylint and Bandit: findings about the target's source.

Both run in the sandbox (ADR 0014), and both need more care than Radon did, because both
have a documented habit of exiting non-zero as a *result* rather than as a failure.

Pylint encodes its outcome in an exit status bitmask: 1 fatal, 2 error, 4 warning,
8 refactor, 16 convention, 32 usage error. Treating any non-zero exit as "the analyser
failed" would discard every run that found something, which is every useful run. Only
bit 0 (fatal) and bit 5 (usage error) mean the tool itself did not work.

Bandit exits 1 when it has findings at or above its severity threshold. Same trap, same
resolution: the JSON is authoritative, the exit status is not.

Severity is normalised at this boundary. Pylint's and Bandit's own vocabularies must not
appear past it -- the report speaks one scale, so a "medium" from one tool and a
"warning" from the other are comparable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import structlog

from app.models.enums import Severity
from app.services.sandbox.result import SandboxResult
from app.services.sandbox.runner import Sandbox

logger = structlog.get_logger(__name__)

PYLINT = "pylint"
BANDIT = "bandit"

#: Pylint's exit status is a bitmask of what it found, not a success flag.
PYLINT_FATAL_BIT = 1
PYLINT_USAGE_ERROR_BIT = 32

#: Pylint message categories onto the one normalised scale. Its "error" is a probable
#: bug; its "convention" and "refactor" are style, which must not outrank a real defect.
PYLINT_SEVERITY: dict[str, Severity] = {
    "fatal": Severity.CRITICAL,
    "error": Severity.MAJOR,
    "warning": Severity.MINOR,
    "refactor": Severity.INFO,
    "convention": Severity.INFO,
    "info": Severity.INFO,
}

#: Bandit reports severity and confidence separately. Only severity maps here;
#: confidence is carried in the message so a low-confidence CRITICAL is still visible
#: as uncertain rather than silently downgraded.
BANDIT_SEVERITY: dict[str, Severity] = {
    "HIGH": Severity.CRITICAL,
    "MEDIUM": Severity.MAJOR,
    "LOW": Severity.MINOR,
    "UNDEFINED": Severity.INFO,
}


@dataclass(frozen=True, slots=True)
class FindingRecord:
    """One issue, already on this project's severity scale."""

    analyzer: str
    rule_id: str
    severity: Severity
    message: str
    #: Repository-relative POSIX path, or None for a project-level finding.
    path: str | None
    line_start: int | None
    line_end: int | None


@dataclass(frozen=True, slots=True)
class FindingsResult:
    """What an analyser produced, and why it produced nothing if it produced nothing.

    An empty ``findings`` list with ``error=None`` means the analyser ran and found
    nothing. An empty list with an ``error`` means it did not run. Constraint C3 turns on
    those being different, because the first is a clean bill of health and the second is
    no information at all.
    """

    analyzer: str
    findings: list[FindingRecord]
    error: str | None = None


def _relative(raw: str, workspace: str = "/workspace") -> str | None:
    """Strip the container's mount prefix off a path the tool reported."""
    if not raw:
        return None
    normalised = raw.replace("\\", "/")
    if normalised.startswith(workspace):
        normalised = normalised[len(workspace) :]
    normalised = normalised.lstrip("/")
    if normalised.startswith("./"):
        normalised = normalised[2:]
    return str(PurePosixPath(normalised)) if normalised else None


def pylint_failed(result: SandboxResult) -> str | None:
    """Whether Pylint itself failed, as opposed to finding problems.

    The distinction the sandbox deliberately does not make: a linter exiting non-zero
    because it found issues is a completed run. Conflating the two is how "pylint found
    83 problems" gets reported as "the analyser failed" and the findings are lost.
    """
    failure = result.describe_failure()
    if failure is not None:
        return f"{PYLINT}: {failure}"
    if result.exit_code is None:
        return f"{PYLINT}: the container was killed before it exited"
    if result.exit_code & PYLINT_USAGE_ERROR_BIT:
        return f"{PYLINT}: usage error: {result.stderr.strip()[:300]}"
    if result.exit_code & PYLINT_FATAL_BIT:
        return f"{PYLINT}: fatal error: {result.stderr.strip()[:300]}"
    return None


def parse_pylint(payload: str) -> FindingsResult:
    """Pylint's `--output-format=json` into findings."""
    if not payload.strip():
        # Pylint prints nothing at all when it has no messages.
        return FindingsResult(analyzer=PYLINT, findings=[])
    try:
        decoded: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        return FindingsResult(
            analyzer=PYLINT, findings=[], error=f"{PYLINT}: output was not valid JSON: {exc}"
        )
    if not isinstance(decoded, list):
        return FindingsResult(
            analyzer=PYLINT,
            findings=[],
            error=f"{PYLINT}: expected a list, got {type(decoded).__name__}",
        )

    findings: list[FindingRecord] = []
    for item in decoded:
        if not isinstance(item, dict):
            continue
        category = str(item.get("type", "info")).lower()
        line = item.get("line")
        end = item.get("endLine")
        findings.append(
            FindingRecord(
                analyzer=PYLINT,
                rule_id=str(item.get("message-id") or item.get("symbol") or "unknown"),
                severity=PYLINT_SEVERITY.get(category, Severity.INFO),
                message=str(item.get("message", "")).strip() or "(no message)",
                path=_relative(str(item.get("path", ""))),
                line_start=int(line) if isinstance(line, int) else None,
                line_end=int(end) if isinstance(end, int) else None,
            )
        )
    return FindingsResult(analyzer=PYLINT, findings=findings)


def bandit_failed(result: SandboxResult) -> str | None:
    """Whether Bandit itself failed. Exit 1 means it found something, not that it broke."""
    failure = result.describe_failure()
    if failure is not None:
        return f"{BANDIT}: {failure}"
    if result.exit_code is None:
        return f"{BANDIT}: the container was killed before it exited"
    if result.exit_code not in (0, 1):
        return f"{BANDIT}: exited {result.exit_code}: {result.stderr.strip()[:300]}"
    return None


def parse_bandit(payload: str) -> FindingsResult:
    """Bandit's `-f json` into findings."""
    if not payload.strip():
        return FindingsResult(
            analyzer=BANDIT, findings=[], error=f"{BANDIT}: produced no output at all"
        )
    try:
        decoded: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        return FindingsResult(
            analyzer=BANDIT, findings=[], error=f"{BANDIT}: output was not valid JSON: {exc}"
        )
    if not isinstance(decoded, dict):
        return FindingsResult(
            analyzer=BANDIT,
            findings=[],
            error=f"{BANDIT}: expected an object, got {type(decoded).__name__}",
        )

    findings: list[FindingRecord] = []
    for item in decoded.get("results", []):
        if not isinstance(item, dict):
            continue
        severity = BANDIT_SEVERITY.get(
            str(item.get("issue_severity", "UNDEFINED")).upper(), Severity.INFO
        )
        confidence = str(item.get("issue_confidence", "UNDEFINED")).upper()
        line = item.get("line_number")
        findings.append(
            FindingRecord(
                analyzer=BANDIT,
                rule_id=str(item.get("test_id", "unknown")),
                severity=severity,
                # Confidence rides in the message rather than discounting the severity:
                # a low-confidence critical is still a critical someone should look at,
                # and silently downgrading it would hide it below the fold.
                message=f"{str(item.get('issue_text', '')).strip()} "
                f"[confidence: {confidence.lower()}]".strip(),
                path=_relative(str(item.get("filename", ""))),
                line_start=int(line) if isinstance(line, int) else None,
                line_end=None,
            )
        )

    # Bandit reports files it could not parse separately from its findings. Those are
    # files nobody scanned, and a report that omits them claims coverage it does not have.
    skipped = decoded.get("errors") or []
    if skipped:
        names = ", ".join(str(entry.get("filename", "?")) for entry in skipped[:3])
        return FindingsResult(
            analyzer=BANDIT,
            findings=findings,
            error=f"{BANDIT}: could not scan {len(skipped)} file(s) (for example: {names})",
        )
    return FindingsResult(analyzer=BANDIT, findings=findings)


def run_pylint(sandbox: Sandbox) -> FindingsResult:
    """Run Pylint over the workspace inside the sandbox."""
    result = sandbox.run(
        [
            "pylint",
            "--output-format=json",
            # Pylint imports what it lints when inference needs it. The sandbox has no
            # network and a read-only root, so an import that reaches out simply fails --
            # this keeps that failure from being reported as a finding about the code.
            "--disable=import-error",
            "--recursive=y",
            "--",
            ".",
        ]
    )
    error = pylint_failed(result)
    if error:
        return FindingsResult(analyzer=PYLINT, findings=[], error=error)
    parsed = parse_pylint(result.stdout)
    logger.info("pylint.done", findings=len(parsed.findings), error=parsed.error)
    return parsed


def run_bandit(sandbox: Sandbox) -> FindingsResult:
    """Run Bandit over the workspace inside the sandbox."""
    result = sandbox.run(["bandit", "-r", "-f", "json", "-q", "--exit-zero", "."])
    error = bandit_failed(result)
    if error:
        return FindingsResult(analyzer=BANDIT, findings=[], error=error)
    parsed = parse_bandit(result.stdout)
    logger.info("bandit.done", findings=len(parsed.findings), error=parsed.error)
    return parsed
