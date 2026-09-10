"""Celery application.

Constraint C2: analysis is asynchronous. A full scan takes minutes, so the API dispatches
a job and returns a job id immediately. There are no synchronous scan endpoints, and this
module is the only place a long-running unit of work may be started from.

Phase 1 defines only a ``ping`` task, to prove the broker round-trip end to end. The scan
pipeline tasks arrive in phase 3.
"""

from __future__ import annotations

from typing import Any

from celery import Celery

from app.config import get_settings


def create_celery_app() -> Celery:
    """Build the Celery app from settings."""
    settings = get_settings()
    app = Celery("codesentinel", broker=settings.broker_url, backend=settings.result_backend)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # A scan must not be silently retried onto another worker mid-flight: a partially
        # written scan is worse than a failed one. Phase 3 handles retries explicitly.
        task_acks_late=False,
        task_reject_on_worker_lost=False,
        # Analysis tasks are long and memory-hungry; one at a time per worker process
        # keeps the sandbox resource limits meaningful.
        worker_prefetch_multiplier=1,
        result_expires=86_400,
    )
    return app


celery_app = create_celery_app()


@celery_app.task(name="codesentinel.ping")
def ping() -> dict[str, Any]:
    """Round-trip check that the broker and a worker are both live."""
    return {"status": "pong"}
