"""Celery application.

Constraint C2: analysis is asynchronous. A full scan takes minutes, so the API dispatches
a job and returns a job id immediately. There are no synchronous scan endpoints, and this
module is the only place a long-running unit of work may be started from.

``ping`` proves the broker round-trip end to end. ``app.workers.tasks`` carries the scan
pipeline entry point and is registered below, because a worker only discovers tasks in
modules it has been told to import -- one that is never imported is a task that silently
does not exist.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from celery import Celery

from app.config import Settings, get_settings


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
        # Without this a worker never imports app.workers.tasks, so codesentinel.run_scan
        # is unregistered and every dispatched scan sits in the queue unreceived.
        imports=("app.workers.tasks",),
        beat_schedule=beat_schedule(settings),
    )
    return app


def beat_schedule(settings: Settings) -> dict[str, Any]:
    """The periodic schedule, which is empty unless retention is switched on.

    The entry is omitted rather than scheduled-and-skipped. A schedule that always
    contains a pruning job makes ``celery inspect scheduled`` say this deployment prunes
    when it does not, and an operator checking whether retention is live would read the
    schedule and conclude it is. Absence is the accurate answer.
    """
    if settings.retention_days <= 0:
        return {}
    return {
        "prune-expired-scans": {
            "task": "codesentinel.prune_scans",
            "schedule": timedelta(hours=settings.retention_interval_hours),
            # A missed run must not stampede on restart: the next one deletes whatever
            # the missed one would have, because the cutoff is computed from the clock
            # rather than from the last run.
            "options": {"expires": settings.retention_interval_hours * 3600},
        }
    }


celery_app = create_celery_app()


@celery_app.task(name="codesentinel.ping")
def ping() -> dict[str, Any]:
    """Round-trip check that the broker and a worker are both live."""
    return {"status": "pong"}
