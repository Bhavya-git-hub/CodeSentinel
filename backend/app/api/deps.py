"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_redis, get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def _redis(settings: SettingsDep) -> Any:
    """The Redis client, as a dependency so tests can substitute a fake.

    A dependency rather than a direct call inside the handler: the rate limiter fails
    closed on an unreachable Redis, which is right in production and would make every
    API unit test a 503 otherwise.
    """
    return await get_redis(settings)


RedisDep = Annotated[Any, Depends(_redis)]
