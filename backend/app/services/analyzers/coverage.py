"""Coverage: running the target's own test suite, offline.

This is the analyser most likely to be unable to run, and the design follows from that
rather than fighting it.

Running a target's tests means executing the target's code -- `conftest.py` runs at
collection time -- so it happens in the sandbox and nowhere else. The sandbox has no
network (ADR 0009) and there is no argument that gives it one, so a target whose suite
needs third-party packages cannot have them installed. That is not a bug to work around;
opening the network to install a hostile repository's declared dependencies would be
executing attacker-chosen package code with network access, which is the single worst
thing this system could do.

So coverage either runs against what the image already provides, or it is recorded as
SKIPPED with the reason. It is never estimated, and a file with no coverage data is never
reported as a file with 0% coverage: the first is unknown, the second is a claim that the
tests exist and do not touch it (constraint C3, anti-pattern #2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import structlog

from app.models.enums import AnalyzerStatus
from app.services.sandbox.result import SandboxResult
from app.services.sandbox.runner import SCRATCH_PATH, Sandbox

logger = structlog.get_logger(__name__)

ANALYZER_NAME = "coverage"

#: pytest's own exit codes. 5 means it collected no tests at all, which is a fact about
#: the target rather than a failure of ours.
PYTEST_NO_TESTS_COLLECTED = 5


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """Per-file line coverage, or the reason there is none.

    ``status`` is explicit rather than inferred from an empty mapping, because "the suite
    ran and covered nothing" and "the suite could not run" are different findings and only
    one of them is about the code.
    """

    status: AnalyzerStatus
    #: Repository-relative POSIX path -> percentage covered. Absent means unmeasured.
    percentages: dict[str, float] = field(default_factory=dict)
    error: str | None = None


def _relative(raw: str, workspace: str = "/workspace") -> str:
    normalised = raw.replace("\\", "/")
    if normalised.startswith(workspace):
        normalised = normalised[len(workspace) :]
    normalised = normalised.lstrip("/")
    if normalised.startswith("./"):
        normalised = normalised[2:]
    return str(PurePosixPath(normalised))


def parse_coverage_json(payload: str) -> CoverageResult:
    """`coverage json` into per-file percentages.

    Only files coverage actually reported appear. A file missing from this mapping keeps
    ``coverage_pct = None`` downstream -- it was not measured, which is not the same as
    being untested.
    """
    try:
        decoded: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        return CoverageResult(
            status=AnalyzerStatus.FAILED,
            error=f"coverage output was not valid JSON: {exc}",
        )
    if not isinstance(decoded, dict) or "files" not in decoded:
        return CoverageResult(
            status=AnalyzerStatus.FAILED,
            error="coverage output had no 'files' section",
        )

    percentages: dict[str, float] = {}
    for raw_path, entry in decoded["files"].items():
        if not isinstance(entry, dict):
            continue
        summary = entry.get("summary")
        if not isinstance(summary, dict):
            continue
        pct = summary.get("percent_covered")
        if isinstance(pct, (int, float)):
            percentages[_relative(str(raw_path))] = float(pct)

    return CoverageResult(status=AnalyzerStatus.SUCCESS, percentages=percentages)


def describe_suite_failure(result: SandboxResult) -> str | None:
    """Why the target's test suite did not produce coverage, in words an operator can use.

    Every branch here ends in SKIPPED rather than FAILED, because none of them is a fault
    in this system: a repository with no tests, or with dependencies we may not install,
    is an ordinary thing to encounter.
    """
    failure = result.describe_failure()
    if failure is not None:
        return f"the test suite {failure}"
    if result.exit_code is None:
        return "the test suite's container was killed before it exited"
    if result.exit_code == PYTEST_NO_TESTS_COLLECTED:
        return "the repository has no tests pytest could collect"
    if result.exit_code != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()
        hint = tail[-1][:200] if tail else "no output"
        # Almost always a missing third-party package. Named rather than guessed at, so
        # the reader can see it is an offline-install limit and not a broken repository.
        return (
            f"the test suite exited {result.exit_code} and produced no coverage. "
            f"The sandbox has no network, so the target's dependencies were not "
            f"installed (ADR 0009). Last output: {hint}"
        )
    return None


def run_coverage(sandbox: Sandbox) -> CoverageResult:
    """Run the target's suite under coverage, or say why it could not.

    Writes to the tmpfs scratch directory: the workspace mount is read-only, and coverage
    insists on a data file.
    """
    run = sandbox.run(
        [
            "python",
            "-m",
            "coverage",
            "run",
            f"--data-file={SCRATCH_PATH}/.coverage",
            "--source=.",
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ]
    )

    reason = describe_suite_failure(run)
    if reason is not None:
        logger.info("coverage.skipped", reason=reason)
        return CoverageResult(status=AnalyzerStatus.SKIPPED, error=reason)

    report = sandbox.run(
        [
            "python",
            "-m",
            "coverage",
            "json",
            f"--data-file={SCRATCH_PATH}/.coverage",
            "-o",
            "-",
        ]
    )
    if report.exit_code != 0:
        return CoverageResult(
            status=AnalyzerStatus.FAILED,
            error=f"coverage could not produce a report: {report.stderr.strip()[:200]}",
        )

    parsed = parse_coverage_json(report.stdout)
    logger.info("coverage.done", files=len(parsed.percentages), status=parsed.status)
    return parsed
