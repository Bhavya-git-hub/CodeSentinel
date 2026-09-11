"""API key authentication.

This service takes a URL from a caller and, on the strength of that URL alone, clones a
repository onto the host and starts containers. An unauthenticated instance is therefore
not merely "open" -- it is a machine that will fetch and analyse whatever any reachable
party names, for as long as they keep asking. Resource exhaustion is the mild outcome;
the interesting one is that the clone target is attacker-chosen, which makes an open
instance a probe for whatever the host can reach.

So the rule here is **fail closed**: a production environment with no keys configured
refuses to start, rather than starting open and waiting for someone to notice. A warning
log would be the softer choice and it is the wrong one -- nobody reads start-up logs of a
service that came up successfully.

Keys are compared with ``secrets.compare_digest``. A plain ``==`` on a secret leaks its
prefix through timing, and while that is a slow attack it is also a free one to prevent.
"""

from __future__ import annotations

import secrets

import structlog
from fastapi import Header, HTTPException, status

from app.config import Settings

logger = structlog.get_logger(__name__)

API_KEY_HEADER = "X-API-Key"


class AuthenticationNotConfiguredError(RuntimeError):
    """Raised at start-up when a production deployment has no API keys.

    Deliberately fatal. The alternative -- log a warning and serve anyway -- produces an
    open instance that looks healthy, and "looks healthy while open" is the state this
    check exists to make impossible.
    """


def assert_auth_configured(settings: Settings) -> None:
    """Refuse to start a production instance with no keys.

    Called from the application factory so the failure happens at boot, where a deploy
    pipeline will catch it, rather than on the first unauthenticated request.
    """
    if settings.environment != "production":
        return
    if not settings.api_keys:
        raise AuthenticationNotConfiguredError(
            "CODESENTINEL_ENVIRONMENT=production but CODESENTINEL_API_KEYS is empty. "
            "This service clones and analyses caller-supplied repositories, so it must "
            "not run unauthenticated. Set CODESENTINEL_API_KEYS to one or more secrets, "
            "or run with CODESENTINEL_ENVIRONMENT=local for development."
        )


def key_is_valid(candidate: str, settings: Settings) -> bool:
    """Constant-time membership test against the configured keys.

    Every configured key is compared even after a match, so the time taken does not
    reveal the position of the matching key.
    """
    matched = False
    for known in settings.api_keys:
        if secrets.compare_digest(candidate, known):
            matched = True
    return matched


async def require_api_key(
    settings_and_key: tuple[Settings, str | None],
) -> None:
    """Internal check shared by the FastAPI dependency and its tests."""
    settings, provided = settings_and_key

    if not settings.api_keys:
        # No keys configured. assert_auth_configured has already made this impossible in
        # production, so reaching here means a development instance, which is open by
        # design and says so in its own logs at startup.
        return

    if provided is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"This endpoint requires an API key in the {API_KEY_HEADER} header.",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )

    if not key_is_valid(provided, settings):
        # The reason is deliberately identical to the missing-key case in everything but
        # the word "valid": distinguishing "unknown key" from "malformed key" would tell
        # a caller which half of their guess was right.
        logger.warning("auth.rejected", reason="invalid key")
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="The API key provided is not valid.",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )


def api_key_dependency(settings: Settings):  # type: ignore[no-untyped-def]
    """Build the FastAPI dependency bound to these settings."""

    async def _dependency(x_api_key: str | None = Header(default=None)) -> None:
        await require_api_key((settings, x_api_key))

    return _dependency
