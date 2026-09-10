"""Liveness and readiness endpoints.

These are deliberately two endpoints, not one. Liveness answers "is this process alive?"
and must never touch a dependency -- a container orchestrator restarting the API because
PostgreSQL is briefly unavailable makes an outage worse. Readiness answers "can this
process serve traffic?" and is what a load balancer and the compose healthcheck use.
"""

from __future__ import annotations

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.config import Settings, get_settings
from app.db import get_engine
from app.schemas.health import DependencyHealth, LivenessResponse, ReadinessResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Report that the process is up. Touches no dependency by design."""
    settings = get_settings()
    return LivenessResponse(version=__version__, environment=settings.environment)


async def _check_database() -> DependencyHealth:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - reason is reported, never swallowed
        logger.warning("readiness.database_unavailable", error=str(exc))
        return DependencyHealth(status="unavailable", error=str(exc))
    return DependencyHealth(status="ok")


async def _check_redis(settings: Settings) -> DependencyHealth:
    client = aioredis.from_url(str(settings.redis_url))
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001 - reason is reported, never swallowed
        logger.warning("readiness.redis_unavailable", error=str(exc))
        return DependencyHealth(status="unavailable", error=str(exc))
    finally:
        await client.aclose()
    return DependencyHealth(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    """Check every dependency and report each one individually.

    Returns 503 when any dependency is down, but still lists the state of all of them --
    a readiness probe that says only "not ready" forces an operator to go looking.
    """
    settings = get_settings()
    dependencies = {
        "database": await _check_database(),
        "redis": await _check_redis(settings),
    }
    ready = all(dep.status == "ok" for dep in dependencies.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "not_ready", dependencies=dependencies)
