"""The Prometheus surface.

The property worth the most here is the one about an unreachable database: a gauge that
cannot be computed is *absent*, not zero. On a dashboard, absent draws a gap and zero
draws a confident flat line at the bottom -- and a flat line at the bottom of
"scans succeeded" is what a working system looks like right before someone concludes
nothing is running. It is anti-pattern #2 with a graph attached.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.metrics import reset_request_counts
from app.config import Settings
from app.db import get_session
from app.main import create_app


class _BrokenSession:
    """A session whose every query raises, standing in for an unreachable PostgreSQL."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("could not connect to server")


class _CountingSession:
    """Answers the two aggregate queries the endpoint makes, in the order it makes them."""

    def __init__(self, *, statuses: list[tuple[Any, int]], repositories: int) -> None:
        self._answers: list[Any] = [_Rows(statuses), _Scalar(repositories)]

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._answers.pop(0)


class _Rows:
    def __init__(self, rows: list[tuple[Any, int]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, int]]:
        return self._rows


class _Scalar:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _Status:
    """Stands in for a ScanStatus member, which the endpoint reads ``.value`` from."""

    def __init__(self, value: str) -> None:
        self.value = value


@pytest.fixture(autouse=True)
def _counters_are_isolated() -> Iterator[None]:
    """The request counter is process-wide; tests must not inherit each other's traffic."""
    reset_request_counts()
    yield
    reset_request_counts()


def _app(settings: Settings, session: Any):  # type: ignore[no-untyped-def]
    application = create_app(settings)

    async def _override() -> AsyncIterator[Any]:
        yield session

    application.dependency_overrides[get_session] = _override
    return application


@pytest_asyncio.fixture
async def enabled_client() -> AsyncIterator[AsyncClient]:
    app = _app(
        Settings(metrics_enabled=True),
        _CountingSession(
            statuses=[(_Status("succeeded"), 7), (_Status("failed"), 2)], repositories=3
        ),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_metrics_are_not_served_unless_enabled() -> None:
    """Absent rather than 404-when-disabled: a 404 and a misrouted scrape look alike."""
    app = _app(Settings(metrics_enabled=False), _BrokenSession())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 404


async def test_metrics_are_off_by_default() -> None:
    assert Settings().metrics_enabled is False


async def test_the_exposition_is_prometheus_text(enabled_client: AsyncClient) -> None:
    response = await enabled_client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE codesentinel_build_info gauge" in response.text


async def test_scan_counts_are_reported_per_status(enabled_client: AsyncClient) -> None:
    body = (await enabled_client.get("/metrics")).text

    assert 'codesentinel_scans{status="succeeded"} 7' in body
    assert 'codesentinel_scans{status="failed"} 2' in body


async def test_the_repository_count_is_reported(enabled_client: AsyncClient) -> None:
    assert "codesentinel_repositories 3" in (await enabled_client.get("/metrics")).text


async def test_a_database_outage_omits_the_gauges_rather_than_zeroing_them() -> None:
    """The central property. Zero is a claim; absence is the truth here."""
    app = _app(Settings(metrics_enabled=True), _BrokenSession())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/metrics")).text

    assert "codesentinel_scans" not in body, "an unknown count was reported as a measurement"
    assert "codesentinel_repositories" not in body
    assert "codesentinel_database_reachable 0" in body


async def test_a_database_outage_still_serves_a_200() -> None:
    """A failed scrape loses the in-process counters and makes a live target look down."""
    app = _app(Settings(metrics_enabled=True), _BrokenSession())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200


async def test_a_reachable_database_says_so(enabled_client: AsyncClient) -> None:
    assert "codesentinel_database_reachable 1" in (await enabled_client.get("/metrics")).text


async def test_requests_are_counted_by_route_template_not_by_path() -> None:
    """An unbounded label eventually kills the scrape target it exists to describe."""
    app = _app(Settings(metrics_enabled=True), _BrokenSession())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/health")
        await client.get("/health")
        body = (await client.get("/metrics")).text

    assert 'route="/health"' in body
    assert 'codesentinel_http_requests_total{method="GET",route="/health",status="200"} 2' in body


async def test_an_unmatched_path_does_not_create_a_series_per_url() -> None:
    """404 probing is the ordinary way an unbounded label set gets filled in."""
    app = _app(Settings(metrics_enabled=True), _BrokenSession())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for suffix in ("a", "b", "c"):
            await client.get(f"/no/such/{suffix}")
        body = (await client.get("/metrics")).text

    assert body.count('route="<unmatched>"') == 1
    assert "/no/such/a" not in body


async def test_no_url_reaches_the_exposition(enabled_client: AsyncClient) -> None:
    """The endpoint is unauthenticated, so everything on it is effectively public.

    Asserted on ``://`` rather than on a specific repository, because the risk is any
    URL-shaped value reaching the series -- a target's clone URL names who this instance
    was pointed at, which is the one genuinely sensitive thing an aggregate could leak.
    """
    body = (await enabled_client.get("/metrics")).text

    assert "://" not in body


async def test_the_build_version_is_published(enabled_client: AsyncClient) -> None:
    """A scrape that cannot say which build produced it cannot attribute a regression."""
    from app import __version__

    assert (
        f'codesentinel_build_info{{version="{__version__}"}} 1'
        in (await enabled_client.get("/metrics")).text
    )
