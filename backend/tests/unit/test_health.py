"""Liveness and readiness endpoints.

The readiness tests stub the dependency checks rather than relying on whether PostgreSQL
and Redis happen to be running. A test that passes only because the developer's Redis is
down is not testing readiness, it is testing the developer's machine -- and it inverts in
CI, where the services are up.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app import __version__
from app.api import health
from app.config import Settings
from app.schemas.health import DependencyHealth


async def test_liveness_is_ok_without_dependencies(client: AsyncClient, settings: Settings) -> None:
    """Liveness must not depend on PostgreSQL or Redis.

    If it did, a brief database outage would make an orchestrator restart every API
    container and turn a degradation into an outage.
    """
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
    }


async def test_liveness_echoes_request_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


async def test_liveness_generates_request_id_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers.get("X-Request-ID")


async def test_readiness_is_200_when_every_dependency_is_up(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _ok(*_args: object, **_kwargs: object) -> DependencyHealth:
        return DependencyHealth(status="ok")

    monkeypatch.setattr(health, "_check_database", _ok)
    monkeypatch.setattr(health, "_check_redis", _ok)

    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {name: dep["status"] for name, dep in body["dependencies"].items()} == {
        "database": "ok",
        "redis": "ok",
    }


async def test_readiness_is_503_when_a_dependency_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One failing dependency is enough to make the instance not ready."""

    async def _down(*_args: object, **_kwargs: object) -> DependencyHealth:
        return DependencyHealth(status="unavailable", error="connection refused")

    async def _ok(*_args: object, **_kwargs: object) -> DependencyHealth:
        return DependencyHealth(status="ok")

    monkeypatch.setattr(health, "_check_database", _down)
    monkeypatch.setattr(health, "_check_redis", _ok)

    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


async def test_readiness_names_the_failing_dependency_and_its_reason(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe that says only 'not ready' forces an operator to go looking.

    The healthy dependencies must still be reported, so the response localises the fault
    rather than merely announcing one.
    """

    async def _down(*_args: object, **_kwargs: object) -> DependencyHealth:
        return DependencyHealth(status="unavailable", error="connection refused")

    async def _ok(*_args: object, **_kwargs: object) -> DependencyHealth:
        return DependencyHealth(status="ok")

    monkeypatch.setattr(health, "_check_database", _ok)
    monkeypatch.setattr(health, "_check_redis", _down)

    body = (await client.get("/health/ready")).json()
    assert body["dependencies"]["database"]["status"] == "ok"
    assert body["dependencies"]["redis"]["status"] == "unavailable"
    assert body["dependencies"]["redis"]["error"] == "connection refused"


async def test_readiness_reports_the_real_reason_when_a_dependency_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure reason must come from the exception, not a generic placeholder.

    Constraint C3's rule -- record the reason, never swallow it -- applies here too.
    """
    monkeypatch.setenv("CODESENTINEL_REDIS_URL", "redis://127.0.0.1:1/0")

    result = await health._check_redis(Settings())
    assert result.status == "unavailable"
    assert result.error


async def test_health_is_not_under_the_versioned_prefix(client: AsyncClient) -> None:
    """Probes are infrastructure; versioning them would break them on every bump."""
    assert (await client.get("/api/v1/health")).status_code == 404
