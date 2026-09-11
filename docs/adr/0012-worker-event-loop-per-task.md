# 0012. Workers run an async body per task under `asyncio.run`, with `NullPool`

**Status:** accepted — 2026-09-11

## Context

Celery tasks are synchronous functions. The data layer is asyncio throughout --
SQLAlchemy 2.x async with asyncpg, and `tests/conftest.py`, `alembic/env.py` and the
FastAPI dependencies all assume it.

Phase 3 is the first phase where a worker touches the database, so the mismatch has to be
resolved rather than deferred.

The obvious resolution is to add `psycopg` and a synchronous `Session` for worker code.
It works, it is well-trodden, and it is a trap: every query in the project could then be
written two ways, and the two would have to be kept in step for the life of the codebase.
Half the eventual test suite would exercise one path while production used the other, and
the divergence would surface as a bug in whichever one was less travelled.

There is also a specific failure mode in the naive async version. A pooled asyncpg
connection created in one event loop and reused in another raises
`... attached to a different loop`. A worker that used the process-wide pooled engine
would therefore succeed on its first task and fail on its second -- which reads as
flakiness rather than as a design error, and is exactly the lesson `tests/conftest.py`
already records for its session-scoped engine fixture.

## Decision

Each Celery task wraps an async body in `asyncio.run()` and builds a **fresh engine with
`NullPool`** for that loop, disposing it in a `finally`.

`build_engine` takes an optional `poolclass` so the worker states this explicitly rather
than duplicating engine construction. `pool_size` and `max_overflow` are only passed when
pooling, because `NullPool` rejects them.

No second database driver is added.

## Consequences

- One driver, one session idiom. A query written for the API works unchanged in a worker.
- An engine and a connection are created per task. Beside a clone and a full history walk
  this is negligible, and it is the price of the guarantee below.
- The "attached to a different loop" failure becomes structurally impossible rather than
  avoided by convention: there is no pool to carry a connection across loops.
- Task bodies must be written async. A future synchronous task that wants the database
  has to adopt the same shape rather than reaching for a sync session.
- The scan id is parsed before the loop starts, so a malformed id fails immediately
  instead of after an engine has been built and a scan half-run.
