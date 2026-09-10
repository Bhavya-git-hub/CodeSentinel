# 0005. Phase 1 ships without local Docker verification

**Status:** accepted — 2026-09-11

## Context

Phase 1's acceptance criteria are: `docker compose up` starts all services,
`alembic upgrade head` succeeds, `pytest` passes, and CI is green.

Docker is not installed on the development machine. Docker Desktop had been installed at
some point -- `%LOCALAPPDATA%\Docker` still holds its logs and `backend.lock` -- but the
binary is gone and WSL reports no installed distributions. Hardware virtualisation is
enabled, so installation is possible, but it needs `wsl --install` and a reboot.

Without a local Docker daemon there is also no local PostgreSQL and no local Redis.

## Decision

Build Phase 1 in full and take **GitHub Actions as the acceptance environment**, which
provides Python 3.11, a real `postgres:15` service, a real `redis:7` service and a Docker
daemon. Specifically:

- `alembic upgrade head`, and every `requires_db` test, run against real PostgreSQL in CI.
- `docker compose config` and `docker compose build` run in CI, proving the compose file
  and Dockerfiles are valid.
- Locally, database-dependent tests **skip with an explicit reason** naming the missing
  `CODESENTINEL_TEST_DATABASE_URL`. SQLite is not substituted: the schema uses JSONB, an
  expression index with `NULLS LAST`, and asyncpg semantics, so a SQLite run would prove
  nothing while appearing green.
- CI fails the build if the `requires_db` tests are skipped there, so the acceptance
  evidence cannot quietly evaporate.

## What is therefore *not* met in phase 1

`docker compose up` has never been executed. The compose file builds and parses, but the
running stack -- service startup ordering, healthchecks, the API reaching PostgreSQL and
Redis by service name -- is unverified. This is stated rather than glossed.

## Consequences

- **Phase 2 is hard-blocked.** Its acceptance criteria are that a container attempting a
  network call fails, that an infinite-loop command is killed at the timeout, and that no
  containers remain after a failed run. None can be demonstrated without a daemon, and
  none can be honestly faked. Docker Desktop must be installed before phase 2 starts.
- Constraint C1 is not exercised by anything in phase 1, because phase 1 executes no
  target-repository code at all.
