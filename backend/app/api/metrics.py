"""Prometheus exposition.

Off unless ``CODESENTINEL_METRICS_ENABLED`` is set, and unauthenticated when on. Those
two facts are one decision: a scraper cannot present a caller key, so the endpoint cannot
be behind the same authentication as the API, and the protection is instead that it does
not exist unless an operator asks for it and carries nothing worth stealing when it does.
Every series here is an aggregate -- no repository URL, no key, no name of who submitted
what. See ADR 0018.

**A gauge this cannot compute is omitted, never reported as zero.** If PostgreSQL is
unreachable, ``codesentinel_scans`` is simply absent from the response and
``codesentinel_database_reachable`` is 0. Prometheus treats an absent series as absent,
so a dashboard shows a gap and an alert on "scans failing" does not fire; emitting 0
would instead assert that there are no scans in any state, which on this system reads as
"nothing is running" rather than "we cannot see". That is anti-pattern #2 with a graph
attached to it, and a graph is harder to argue with than a number.

The exposition text is written here rather than taken from ``prometheus_client``. The
format for counters and gauges is a handful of lines, every label value in this module
comes from a closed enum, so no escaping case can arise, and the alternative is a
dependency plus its multiprocess-registry machinery for four series.
"""

from __future__ import annotations

from collections import Counter

import structlog
from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.api.deps import SessionDep
from app.models.repository import Repository, Scan

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["metrics"])

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

#: Requests served by this process, keyed by (route template, status code). The route
#: template rather than the request path: `/api/v1/scans/{scan_id}` is one series, while
#: the raw path would be one series per scan id and would eventually take out the
#: scrape target it is supposed to describe.
_requests: Counter[tuple[str, str, int]] = Counter()


def record_request(method: str, route: str, status_code: int) -> None:
    """Count one served request. Called from the middleware in ``app.main``."""
    _requests[(method, route, status_code)] += 1


def reset_request_counts() -> None:
    """Clear the in-process counters. For tests, which must not see each other's traffic."""
    _requests.clear()


def _line(name: str, value: float, **labels: str) -> str:
    """One sample. Label values come from closed sets, so no escaping is needed."""
    if not labels:
        return f"{name} {value}"
    rendered = ",".join(f'{key}="{val}"' for key, val in sorted(labels.items()))
    return f"{name}{{{rendered}}} {value}"


async def _scan_counts(session: AsyncSession) -> dict[str, int] | None:
    """Scans grouped by status, or None if the database could not answer.

    None rather than an empty dict: an empty dict is a real measurement of a database
    with no scans in it, and the caller renders the two differently on purpose.
    """
    try:
        rows = (
            await session.execute(select(Scan.status, func.count()).group_by(Scan.status))
        ).all()
    except Exception as exc:  # noqa: BLE001 - surfaced as database_reachable 0 plus this log
        logger.warning("metrics.database_unavailable", error=str(exc))
        return None
    return {str(status.value): int(count) for status, count in rows}


async def _repository_count(session: AsyncSession) -> int | None:
    """Repositories known, or None if the database could not answer."""
    try:
        result = await session.execute(select(func.count()).select_from(Repository))
    except Exception as exc:  # noqa: BLE001 - surfaced as database_reachable 0 plus this log
        logger.warning("metrics.database_unavailable", error=str(exc))
        return None
    return int(result.scalar_one())


@router.get("/metrics")
async def metrics(session: SessionDep) -> Response:
    """Current values, in Prometheus text format.

    Returns 200 even when the database is unreachable. A scrape failure would lose the
    request counters too -- which are in-process and still perfectly good -- and would
    make the target look down when it is up and serving. The database's state is a
    series of its own instead, which is the thing to alert on.
    """
    lines: list[str] = [
        "# HELP codesentinel_build_info Build information; always 1.",
        "# TYPE codesentinel_build_info gauge",
        _line("codesentinel_build_info", 1, version=__version__),
    ]

    scan_counts = await _scan_counts(session)
    repositories = await _repository_count(session)
    reachable = scan_counts is not None and repositories is not None

    lines += [
        "# HELP codesentinel_database_reachable 1 when the last scrape could read the database.",
        "# TYPE codesentinel_database_reachable gauge",
        _line("codesentinel_database_reachable", 1 if reachable else 0),
    ]

    if scan_counts is not None:
        lines += [
            "# HELP codesentinel_scans Scans recorded, by status. Absent if unreadable.",
            "# TYPE codesentinel_scans gauge",
        ]
        # Only statuses actually present are emitted. A status with no scans is a real
        # zero and PostgreSQL simply does not return a row for it, which is the same
        # thing; inventing the missing rows here would be inventing measurements.
        lines += [
            _line("codesentinel_scans", count, status=status)
            for status, count in sorted(scan_counts.items())
        ]

    if repositories is not None:
        lines += [
            "# HELP codesentinel_repositories Repositories known to this instance.",
            "# TYPE codesentinel_repositories gauge",
            _line("codesentinel_repositories", repositories),
        ]

    lines += [
        "# HELP codesentinel_http_requests_total Requests served by this process.",
        "# TYPE codesentinel_http_requests_total counter",
    ]
    lines += [
        _line(
            "codesentinel_http_requests_total",
            count,
            method=method,
            route=route,
            status=str(status_code),
        )
        for (method, route, status_code), count in sorted(_requests.items())
    ]

    return Response(content="\n".join(lines) + "\n", media_type=CONTENT_TYPE)
