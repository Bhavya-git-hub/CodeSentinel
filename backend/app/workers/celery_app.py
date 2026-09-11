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

import contextlib
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import structlog
from celery import Celery
from celery.signals import worker_init

from app.config import Settings, get_settings

logger = structlog.get_logger(__name__)


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


class CloneRootUnusableError(RuntimeError):
    """Raised at worker start-up when the clone root cannot be written to.

    Deliberately fatal, and the reason is the first real deployment: the clone directory
    came up owned by root while the worker runs as uid 10001, so every scan died on
    mkdtemp. The pipeline now records that as a FAILED scan with its reason, which is
    correct and is still too late -- the operator finds out one scan at a time, from the
    API, for a mistake that was already true before any work was accepted.

    A bind-mounted directory cannot inherit ownership from the image, so nothing in the
    build can fix this and nothing in compose can check it. A worker that refuses to
    start is the only place the check can live where it is cheap and unmissable.
    """


@worker_init.connect
def check_clone_root(**_kwargs: Any) -> None:
    """Prove the worker can actually write where clones go, before it takes any work.

    Writes a probe file rather than calling ``os.access``: access(2) answers about mode
    bits, and this path is routinely a bind mount whose real behaviour depends on
    ownership the image cannot set. The only honest test of "can I write here" is to
    write.

    Registered in this module rather than in ``tasks``: this is the ``-A`` target, so it
    is imported before the worker starts, whereas ``imports=`` modules are loaded later
    and might miss the signal entirely.
    """
    settings = get_settings()
    root = Path(settings.clone_root)
    probe = root / f".codesentinel-writable-{os.getpid()}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe.touch()
    except OSError as exc:
        raise CloneRootUnusableError(
            f"The clone root {root} is not writable by the user this worker runs as: "
            f"{exc}. Every scan would fail on the first clone. Under Docker this is a "
            f"bind-mounted host directory, which takes the host's ownership and cannot "
            f"inherit the image's -- create it and chown it to the image's uid before "
            f"starting. docs/DEPLOYMENT.md step 2 has the command."
        ) from exc
    finally:
        # Best effort. A probe left behind is harmless -- the pipeline creates its own
        # subdirectory per scan and never reads this one -- and failing to remove it must
        # not turn a successful check into a refusal to start.
        with contextlib.suppress(OSError):
            probe.unlink()

    # Logged on success, not only on failure. A guard that is silent when it passes cannot
    # be distinguished from a guard that never ran -- and this one is wired through a
    # signal, so "never ran" is a single missing import away and would look exactly like a
    # healthy worker.
    logger.info("worker.clone_root_writable", clone_root=str(root))


celery_app = create_celery_app()


@celery_app.task(name="codesentinel.ping")
def ping() -> dict[str, Any]:
    """Round-trip check that the broker and a worker are both live."""
    return {"status": "pong"}
