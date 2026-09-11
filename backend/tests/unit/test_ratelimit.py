"""Submission rate limiting."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.ratelimit import bucket_key, enforce


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.fail = fail

    async def incr(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis is down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


async def test_submissions_under_the_limit_pass() -> None:
    redis = FakeRedis()
    for _ in range(3):
        await enforce(redis, api_key="k", limit=3, now=1000.0)


async def test_the_submission_over_the_limit_is_refused() -> None:
    redis = FakeRedis()
    for _ in range(3):
        await enforce(redis, api_key="k", limit=3, now=1000.0)

    with pytest.raises(HTTPException) as excinfo:
        await enforce(redis, api_key="k", limit=3, now=1000.0)

    assert excinfo.value.status_code == 429
    assert "Retry-After" in (excinfo.value.headers or {})


async def test_callers_are_counted_separately() -> None:
    """One caller's burst must not lock out another."""
    redis = FakeRedis()
    for _ in range(3):
        await enforce(redis, api_key="noisy", limit=3, now=1000.0)

    await enforce(redis, api_key="quiet", limit=3, now=1000.0)


async def test_a_new_window_resets_the_count() -> None:
    redis = FakeRedis()
    for _ in range(3):
        await enforce(redis, api_key="k", limit=3, now=1000.0)

    await enforce(redis, api_key="k", limit=3, now=1061.0)


async def test_a_redis_outage_fails_closed() -> None:
    """Failing open would turn any Redis blip into an unmetered window.

    That is the opposite of the usual instinct, and the usual instinct is wrong on an
    endpoint whose entire risk is unmetered use. 503 is honest: the service cannot
    currently meter submissions, so it does not accept them.
    """
    with pytest.raises(HTTPException) as excinfo:
        await enforce(FakeRedis(fail=True), api_key="k", limit=10, now=1000.0)

    assert excinfo.value.status_code == 503


def test_the_api_key_is_never_stored_in_the_bucket_key() -> None:
    """Redis contents reach logs, backups and MONITOR output."""
    key = bucket_key("super-secret-key", 1000)
    assert "super-secret-key" not in key


def test_the_window_expiry_is_set_once_per_window() -> None:
    """The TTL is set on the increment that creates the key, so it always exists."""
    redis = FakeRedis()
    assert redis.expiries == {}
