"""Liveness and readiness endpoints."""

from __future__ import annotations

from httpx import AsyncClient

from app import __version__


async def test_liveness_is_ok_without_dependencies(client: AsyncClient) -> None:
    """Liveness must not depend on PostgreSQL or Redis.

    If it did, a brief database outage would make an orchestrator restart every API
    container and turn a degradation into an outage.
    """
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "version": __version__, "environment": "local"}


async def test_liveness_echoes_request_id(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


async def test_liveness_generates_request_id_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers.get("X-Request-ID")


async def test_readiness_reports_503_when_dependencies_are_down(client: AsyncClient) -> None:
    """With no database or Redis in this environment, readiness must say so."""
    response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert set(body["dependencies"]) == {"database", "redis"}


async def test_readiness_names_each_failing_dependency(client: AsyncClient) -> None:
    """A probe that says only 'not ready' forces an operator to go looking."""
    body = (await client.get("/health/ready")).json()
    for name, dependency in body["dependencies"].items():
        assert dependency["status"] == "unavailable", name
        assert dependency["error"], f"{name} reported no reason for being unavailable"


async def test_health_is_not_under_the_versioned_prefix(client: AsyncClient) -> None:
    """Probes are infrastructure; versioning them would break them on every bump."""
    assert (await client.get("/api/v1/health")).status_code == 404
