"""The worker entry point. The pipeline is stubbed; the loop management is the subject."""

from __future__ import annotations

import uuid

import pytest

from app.workers import tasks


def test_the_task_runs_the_async_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """asyncio.run owns the loop, so a task never inherits a dirty one from its
    predecessor."""
    seen: list[uuid.UUID] = []

    async def fake_run(session: object, scan_id: uuid.UUID, *, settings: object) -> None:
        seen.append(scan_id)

    monkeypatch.setattr(tasks, "run_ingestion", fake_run)
    scan_id = uuid.uuid4()
    tasks.run_scan(str(scan_id))
    assert seen == [scan_id]


def test_an_invalid_scan_id_is_rejected_before_any_work() -> None:
    with pytest.raises(ValueError):
        tasks.run_scan("not-a-uuid")
