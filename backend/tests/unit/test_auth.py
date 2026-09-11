"""API key authentication.

The property that matters most is the one asserted first: a production instance with no
keys must refuse to start. Everything else here is ordinary.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import AuthenticationNotConfiguredError, assert_auth_configured, key_is_valid
from app.config import Settings
from app.main import create_app


def test_production_without_keys_refuses_to_start() -> None:
    """Fail closed. A warning log would let an open instance look healthy.

    This service clones and analyses whatever a caller names, so an unauthenticated
    production instance is a machine that fetches arbitrary URLs for anyone who can reach
    it. Nobody reads the start-up logs of a service that came up fine.
    """
    with pytest.raises(AuthenticationNotConfiguredError) as excinfo:
        assert_auth_configured(Settings(environment="production", api_keys=[]))

    # The message has to tell an operator what to do, not just that something is wrong.
    assert "CODESENTINEL_API_KEYS" in str(excinfo.value)


def test_production_with_keys_starts() -> None:
    # Returns None; the assertion is that it does not raise.
    assert_auth_configured(Settings(environment="production", api_keys=["s3cret"]))


def test_local_without_keys_is_allowed() -> None:
    """Development must not require key management to run the thing at all."""
    assert_auth_configured(Settings(environment="local", api_keys=[]))


def test_a_known_key_validates() -> None:
    settings = Settings(api_keys=["alpha", "beta"])
    assert key_is_valid("beta", settings) is True


def test_an_unknown_key_does_not_validate() -> None:
    assert key_is_valid("gamma", Settings(api_keys=["alpha", "beta"])) is False


def test_a_prefix_of_a_key_does_not_validate() -> None:
    """compare_digest is exact; a truncated guess must not pass."""
    assert key_is_valid("alph", Settings(api_keys=["alpha"])) is False


def test_keys_survive_a_comma_separated_env_value() -> None:
    """They arrive through the environment in every real deployment."""
    assert Settings(api_keys="one,two,three").api_keys == ["one", "two", "three"]


def test_keys_are_not_written_into_the_reproducibility_snapshot() -> None:
    """That snapshot is persisted on every scan row; a secret there is in every backup."""
    snapshot = Settings(api_keys=["s3cret"]).reproducibility_snapshot()
    assert "api_keys" not in snapshot
    assert "s3cret" not in str(snapshot)


async def _client(settings: Settings) -> AsyncClient:
    """A client over an app built with these settings.

    The rate limiter's Redis is overridden here too: this module builds its own app
    rather than using the shared fixture, so the autouse override in conftest does not
    reach it, and the limiter would fail closed on the absent server before auth ever
    ran.
    """
    from app.api.deps import _redis
    from tests.conftest import _MemoryRedis

    application = create_app(settings)
    memory = _MemoryRedis()

    async def _override() -> object:
        return memory

    application.dependency_overrides[_redis] = _override
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


async def test_a_request_without_a_key_is_refused_when_keys_are_configured() -> None:
    async with await _client(Settings(api_keys=["s3cret"])) as client:
        response = await client.post("/api/v1/scans", json={"url": "https://example.com/a/b"})

    assert response.status_code == 401
    assert "X-API-Key" in response.headers.get("www-authenticate", "")


async def test_a_request_with_a_wrong_key_is_refused() -> None:
    async with await _client(Settings(api_keys=["s3cret"])) as client:
        response = await client.post(
            "/api/v1/scans",
            json={"url": "https://example.com/a/b"},
            headers={"X-API-Key": "wrong"},
        )

    assert response.status_code == 401


async def test_a_valid_key_gets_past_authentication() -> None:
    """It then fails on the database, which is the point: auth is no longer the blocker."""
    async with await _client(Settings(api_keys=["s3cret"])) as client:
        response = await client.post(
            "/api/v1/scans",
            json={"url": "ext::sh -c whoami"},
            headers={"X-API-Key": "s3cret"},
        )

    # 422 is the URL refusal, which only happens after the key was accepted.
    assert response.status_code == 422


async def test_health_probes_stay_unauthenticated() -> None:
    """An orchestrator cannot present a key, and readiness reveals only reachability."""
    async with await _client(Settings(api_keys=["s3cret"])) as client:
        response = await client.get("/health")

    assert response.status_code != 401
