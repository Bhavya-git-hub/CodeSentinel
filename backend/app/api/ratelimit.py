"""Submission rate limiting.

A scan costs a clone, a full history walk and several containers. A caller who can queue
without bound exhausts the worker pool using requests that are individually legitimate,
so there is nothing for the URL validator or the sandbox to refuse -- the abuse is in the
arrival rate, and only something counting arrivals can see it.

The counter lives in Redis rather than in process memory, because the API is expected to
run more than one replica and a per-process counter multiplies the real limit by the
replica count while appearing to work.

**It fails closed on a Redis outage.** The instinct is the opposite -- do not let the
rate limiter take down the service -- and it is wrong here: failing open turns any Redis
blip into an unmetered window on an endpoint whose whole risk is unmetered use. The API
already reports itself unready when Redis is unreachable, so an outage is visible as an
outage rather than silently becoming an open door.
"""

from __future__ import annotations

import hashlib

import structlog
from fastapi import HTTPException, status

logger = structlog.get_logger(__name__)

WINDOW_SECONDS = 60


def bucket_key(api_key: str | None, window_start: int) -> str:
    """The Redis key for one caller's current window.

    The API key is hashed, never stored. Redis contents reach logs, backups and
    `MONITOR` output, and a rate-limit counter is not worth putting a live credential in
    all three. A truncated SHA-256 is ample to separate callers.
    """
    identity = hashlib.sha256((api_key or "anonymous").encode()).hexdigest()[:16]
    return f"codesentinel:ratelimit:{identity}:{window_start}"


async def enforce(
    redis_client: object,
    *,
    api_key: str | None,
    limit: int,
    now: float,
) -> None:
    """Count this submission, refusing once the caller is over the limit.

    A fixed window rather than a sliding one: it permits a burst of up to 2x the limit
    across a window boundary, which is an acceptable trade for a counter that is one
    INCR and cannot drift between replicas.
    """
    window_start = int(now // WINDOW_SECONDS) * WINDOW_SECONDS
    key = bucket_key(api_key, window_start)

    try:
        # incr then expire: the key is created by the first increment of each window, so
        # the TTL is set on a key that definitely exists.
        count = await redis_client.incr(key)  # type: ignore[attr-defined]
        if count == 1:
            await redis_client.expire(key, WINDOW_SECONDS * 2)  # type: ignore[attr-defined]
    except Exception as exc:
        # Fail closed. See the module docstring: an open window during a Redis blip is
        # exactly the condition this limiter exists to prevent.
        logger.error("ratelimit.backend_unavailable", error=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Submissions are temporarily unavailable: the rate limiter's backend "
                "could not be reached. Existing scans are unaffected."
            ),
        ) from exc

    if count > limit:
        retry_after = int(window_start + WINDOW_SECONDS - now) + 1
        logger.info("ratelimit.exceeded", count=count, limit=limit)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit reached: {limit} scan submissions per minute. "
                f"Try again in {retry_after}s."
            ),
            headers={"Retry-After": str(retry_after)},
        )
