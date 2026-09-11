"""The filtering Docker socket proxy.

Deployed from the backend image with a different command. It is the only component that
holds the Docker socket; the worker reaches it over TCP and has no socket of its own.

Thin on purpose. Every decision lives in ``socket_filter.validate``, which is a pure
function with no I/O, so the security-critical part can be read and tested without a
daemon. This module does transport and nothing else -- if you are reviewing the control,
read the filter, not this.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.config import get_settings
from app.logging import configure_logging
from app.services.sandbox.socket_filter import validate

logger = structlog.get_logger(__name__)

DOCKER_SOCKET = "/var/run/docker.sock"

#: Hop-by-hop headers must not be forwarded; the client and the daemon negotiate their
#: own. Passing them through produces a connection that both ends believe is upgraded.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


def _client() -> httpx.AsyncClient:
    """A client bound to the Docker socket.

    The base URL is a placeholder: the transport is a unix socket, so the host in the URL
    is never resolved. It has to be syntactically valid, nothing more.
    """
    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET),
        base_url="http://docker",
        timeout=httpx.Timeout(None),
    )


async def forward(request: Request) -> Response:
    """Validate, then forward. Refusals never reach the daemon."""
    raw = await request.body()

    body: Any = None
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            # A create request must be JSON. Anything else is either not a create -- in
            # which case validate ignores the body -- or malformed, and a malformed body
            # is not something to guess at.
            body = None

    verdict = validate(request.method, request.url.path, body)
    if not verdict.allowed:
        # Logged at error: a refusal here means something asked the daemon for more than
        # the sandbox ever needs, and that is worth waking up for.
        logger.error(
            "socket_proxy.refused",
            method=request.method,
            path=request.url.path,
            reason=verdict.reason,
        )
        return JSONResponse({"message": f"refused by CodeSentinel: {verdict.reason}"}, 403)

    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}

    async with _client() as client:
        upstream = await client.request(
            request.method,
            request.url.path,
            params=dict(request.query_params),
            content=raw or None,
            headers=headers,
        )

    passthrough = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP}
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=passthrough,
        media_type=upstream.headers.get("content-type"),
    )


def create_proxy() -> Starlette:
    configure_logging(get_settings())
    logger.info("socket_proxy.start", socket=DOCKER_SOCKET)
    return Starlette(
        routes=[
            Route(
                "/{path:path}",
                forward,
                methods=["GET", "POST", "DELETE", "HEAD", "PUT"],
            )
        ]
    )


app = create_proxy()
