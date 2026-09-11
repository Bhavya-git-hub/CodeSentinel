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
import os
import socket as socketlib
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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


class SocketUnreachableError(RuntimeError):
    """Raised at start-up when the proxy cannot open the Docker socket.

    Deliberately fatal, and the reason is the first real ``docker compose up``: the proxy
    runs unprivileged, ``/var/run/docker.sock`` is ``root:docker`` mode 660, and nothing
    put this process in that group -- so it started cleanly, reported itself up, and
    returned 500 to every request for the life of the deployment.

    Nothing downstream could say so either. The worker translated the 500 into "the
    sandbox was unavailable", the pipeline recorded PARTIAL with that reason, and the
    report said every file was unmeasured -- all of it correct, none of it pointing at a
    group id. A component that answers requests while being unable to do its only job is
    the exact shape this project refuses elsewhere (ADR 0016), and it is refused here for
    the same reason: a deployment that does not start gets investigated.
    """


def assert_socket_reachable(path: str = DOCKER_SOCKET) -> None:
    """Fail loudly at boot if the Docker socket is missing or not usable by this process.

    Connects rather than calling ``os.access``: access(2) answers about the file's mode
    bits, and a socket can be readable-looking and still refuse a connection. The only
    honest test of "can I talk to the daemon" is to talk to it.
    """
    if not os.path.exists(path):
        raise SocketUnreachableError(
            f"{path} does not exist. The proxy is the only component that may hold the "
            f"Docker socket, so it must be bind-mounted into this container."
        )

    # AF_UNIX, getuid and getgroups are POSIX-only, and this module only ever runs in a
    # Linux container -- but mypy also type-checks it on a Windows development machine,
    # where those attributes do not exist. Reached through getattr so the platform check
    # stays a runtime fact rather than becoming a type error on the wrong OS.
    af_unix = getattr(socketlib, "AF_UNIX", None)
    if af_unix is None:  # pragma: no cover - the proxy is deployed only on Linux
        raise SocketUnreachableError(
            "This platform has no AF_UNIX support, so the Docker socket cannot be "
            "reached. The proxy is a Linux container; it is not runnable here."
        )

    probe = socketlib.socket(af_unix, socketlib.SOCK_STREAM)
    try:
        probe.connect(path)
    except OSError as exc:
        mode = ""
        try:
            info = os.stat(path)
            uid = getattr(os, "getuid", lambda: "unknown")()
            groups: list[int] = getattr(os, "getgroups", list)()
            mode = (
                f" It is owned by uid {info.st_uid} gid {info.st_gid} with mode "
                f"{stat.filemode(info.st_mode)}; this process runs as uid {uid} "
                f"in groups {sorted(groups)}."
            )
        except OSError:
            # The stat is a courtesy for the operator; its failure must not replace the
            # connection error, which is the thing that actually went wrong.
            pass
        raise SocketUnreachableError(
            f"Cannot connect to the Docker socket at {path}: {exc}.{mode} On Docker this "
            f"is usually the socket's group: add the host's docker gid to the proxy "
            f"service with group_add, which is the least privilege that works -- running "
            f"this container as root would also work and gives uid 0 to the one process "
            f"that holds the daemon."
        ) from exc
    finally:
        probe.close()


@asynccontextmanager
async def _lifespan(_app: Starlette) -> AsyncIterator[None]:
    """Check the socket when the server starts, not when the module is imported.

    In the lifespan rather than in ``create_proxy`` because ``app`` is built at module
    scope: doing it there would make importing this module require a live Docker socket,
    which breaks every test and every type check on a machine that has none. Uvicorn
    treats an exception here as a failed start-up and exits, so the container does not
    come up -- which is the behaviour wanted, without making import mean start.
    """
    assert_socket_reachable()
    logger.info("socket_proxy.start", socket=DOCKER_SOCKET)
    yield


def create_proxy() -> Starlette:
    configure_logging(get_settings())
    return Starlette(
        lifespan=_lifespan,
        routes=[
            Route(
                "/{path:path}",
                forward,
                methods=["GET", "POST", "DELETE", "HEAD", "PUT"],
            )
        ],
    )


app = create_proxy()
