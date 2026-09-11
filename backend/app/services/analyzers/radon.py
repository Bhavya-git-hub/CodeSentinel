"""Radon: cyclomatic complexity and maintainability index.

Runs inside the sandbox. Radon only reads source and imports nothing from it, so it is
tempting to run on the host -- but ADR 0011 drew the C1 line at executing target code
rather than at a per-tool risk assessment, and "this particular analyser is safe enough"
is a judgement that gets made once per tool until one of them is wrong. Analysers run in
the container.

Radon reports per-file failures **inline**, as ``{"path": {"error": "..."}}``, and still
exits zero. A parser that assumes every value is a list of blocks therefore crashes or
silently drops files -- and the dropped ones are the unparseable, half-migrated,
syntactically broken files that a review queue most wants to surface.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import structlog

from app.config import Settings
from app.services.sandbox.result import SandboxResult
from app.services.sandbox.runner import Sandbox

logger = structlog.get_logger(__name__)

ANALYZER_NAME = "radon"

#: Radon's documented bounds for the maintainability index. Its underlying formula can
#: produce values outside this range, and the column is documented as 0-100.
MI_MIN = 0.0
MI_MAX = 100.0


@dataclass(frozen=True, slots=True)
class MetricResult:
    """Per-file values, per-file failures, and whole-tool failure, kept apart.

    Three different facts. ``values`` missing a path because Radon could not parse it is
    not the same as Radon never having run, and neither is the same as a file genuinely
    measuring zero. Collapsing them is how a scan reports a clean result for code nobody
    successfully analysed.
    """

    values: dict[str, float] = field(default_factory=dict)
    #: path -> why that one file could not be measured.
    errors: dict[str, str] = field(default_factory=dict)
    #: Set when the tool itself failed: non-zero exit, timeout, unreadable output.
    tool_error: str | None = None


def _normalise(raw_path: str) -> str:
    """Radon prefixes paths with './'; the database stores repository-relative POSIX."""
    return str(PurePosixPath(raw_path.replace("\\", "/").removeprefix("./")))


def _loads(payload: str) -> tuple[dict[str, Any] | None, str | None]:
    """Decode Radon's output, returning the reason rather than raising."""
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"Radon output was not valid JSON: {exc}"
    if not isinstance(decoded, dict):
        return None, f"Radon output was {type(decoded).__name__}, expected an object"
    return decoded, None


def parse_complexity(payload: str) -> MetricResult:
    """``radon cc -j`` into per-file total cyclomatic complexity.

    The total, not the mean or the max. A file with forty simple functions offers more
    places to be wrong than one with three, and the mean divides that back out again. The
    max answers a different question -- "where is the worst function" -- which phase 7 can
    ask of the raw blocks.
    """
    decoded, error = _loads(payload)
    if decoded is None:
        return MetricResult(tool_error=error)

    values: dict[str, float] = {}
    errors: dict[str, str] = {}

    for raw_path, entry in decoded.items():
        path = _normalise(raw_path)
        if isinstance(entry, dict):
            errors[path] = str(entry.get("error", "Radon reported an unspecified failure"))
            continue
        if not isinstance(entry, list):
            errors[path] = f"unexpected Radon entry of type {type(entry).__name__}"
            continue
        # An empty block list is a real zero: there is genuinely nothing to branch on.
        values[path] = float(sum(block.get("complexity", 0) for block in entry))

    return MetricResult(values=values, errors=errors)


def parse_maintainability(payload: str) -> MetricResult:
    """``radon mi -j`` into per-file maintainability index, clamped to 0-100."""
    decoded, error = _loads(payload)
    if decoded is None:
        return MetricResult(tool_error=error)

    values: dict[str, float] = {}
    errors: dict[str, str] = {}

    for raw_path, entry in decoded.items():
        path = _normalise(raw_path)
        if not isinstance(entry, dict):
            errors[path] = f"unexpected Radon entry of type {type(entry).__name__}"
            continue
        if "error" in entry:
            errors[path] = str(entry["error"])
            continue
        if "mi" not in entry:
            errors[path] = "Radon reported no maintainability index for this file"
            continue
        values[path] = min(MI_MAX, max(MI_MIN, float(entry["mi"])))

    return MetricResult(values=values, errors=errors)


def _result_or_error(result: SandboxResult, what: str) -> str | None:
    """Turn a non-usable sandbox run into a reason string, or None if it is usable.

    A linter exiting non-zero because it found issues is a completed run; Radon exiting
    non-zero is not, since it has no findings to report. The distinction lives here rather
    than in the sandbox, which deliberately does not know tool semantics.
    """
    failure = result.describe_failure()
    if failure is not None:
        return f"{what}: {failure}"
    if result.exit_code != 0:
        return f"{what}: radon exited {result.exit_code}: {result.stderr.strip()[:300]}"
    if result.stdout_truncated:
        # Truncated JSON does not parse, and a partial parse would be worse if it did.
        return f"{what}: Radon output exceeded the capture limit and was truncated"
    return None


def measure(sandbox: Sandbox, settings: Settings) -> tuple[MetricResult, MetricResult]:
    """Run both Radon passes in the sandbox and parse them.

    Two containers rather than one shell invocation joining them: the sandbox runs one
    command per container by design, and a shell would be a place for a target's
    environment to intervene.
    """
    del settings  # bounds come from the sandbox's own configuration

    cc_result = sandbox.run(["radon", "cc", "-j", "--", "."])
    cc_error = _result_or_error(cc_result, "cyclomatic complexity")
    complexity = (
        MetricResult(tool_error=cc_error) if cc_error else parse_complexity(cc_result.stdout)
    )

    mi_result = sandbox.run(["radon", "mi", "-j", "--", "."])
    mi_error = _result_or_error(mi_result, "maintainability index")
    maintainability = (
        MetricResult(tool_error=mi_error) if mi_error else parse_maintainability(mi_result.stdout)
    )

    logger.info(
        "radon.measured",
        files_measured=len(complexity.values),
        files_failed=len(complexity.errors),
        tool_error=complexity.tool_error,
    )
    return complexity, maintainability
