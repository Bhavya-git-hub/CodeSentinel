"""FastAPI application factory."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health, metrics
from app.api.auth import api_key_dependency, assert_auth_configured
from app.api.v1 import api_router
from app.config import Settings, get_settings
from app.db import get_engine
from app.logging import configure_logging

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down.

    Deliberately does *not* connect to the database on start-up. The API must come up and
    report itself unready via /health/ready rather than crash-looping while PostgreSQL is
    still starting.
    """
    settings: Settings = app.state.settings
    logger.info("app.startup", environment=settings.environment, version=__version__)
    try:
        yield
    finally:
        await get_engine().dispose()
        logger.info("app.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    A factory rather than a module-level singleton so tests can construct isolated
    instances with different settings.
    """
    settings = settings or get_settings()
    configure_logging(settings)
    # Before anything else: a production instance with no keys must not come up.
    assert_auth_configured(settings)

    app = FastAPI(
        title="CodeSentinel",
        version=__version__,
        description="Code review and quality intelligence platform",
        lifespan=_lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Bind a request id to the logging context and echo it back.

        A scan spans an API request and a Celery task; a correlating id is what makes the
        two halves of that story joinable in the logs.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
            if settings.metrics_enabled:
                # The route template, not request.url.path: the raw path is one series
                # per scan id, which is an unbounded label and eventually kills the
                # scrape target it exists to describe. A request that matched no route
                # is counted under a single bucket for the same reason.
                route = getattr(request.scope.get("route"), "path", "<unmatched>")
                metrics.record_request(request.method, route, response.status_code)
        finally:
            # api_key_name is bound by the auth dependency, which runs inside this
            # middleware. Unbinding it here rather than there keeps the request context
            # torn down in one place, and unbind tolerates a key that was never set --
            # which is every unauthenticated request, including the health probes.
            structlog.contextvars.unbind_contextvars("request_id", "path", "api_key_name")
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.include_router(health.router)
    if settings.metrics_enabled:
        # Registered conditionally rather than served conditionally. An always-present
        # /metrics that answers 404 when disabled is indistinguishable from one that is
        # enabled but misrouted, and an operator debugging a scrape needs those apart.
        # Unauthenticated, like the health probes and for the same reason: a scraper has
        # no key to present. ADR 0018 says what that costs and why it is acceptable.
        app.include_router(metrics.router)
        logger.info("metrics.enabled", path="/metrics")
    # Health probes stay unauthenticated -- an orchestrator cannot present a key,
    # and they reveal only whether dependencies are reachable.
    app.include_router(
        api_router,
        prefix=settings.api_v1_prefix,
        dependencies=[Depends(api_key_dependency(settings))],
    )
    return app
