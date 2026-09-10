# Phase 1 — Foundation

## Scope delivered

- Project scaffold per section 4 of the brief; packages for later phases created empty.
- `pydantic-settings` configuration with a `reproducibility_snapshot()` for constraint C5.
- Full data model: all eight tables at the scan/commit/file grain, SQLAlchemy 2.x async.
- Alembic async environment and a hand-reviewed initial migration.
- `/health` (liveness) and `/health/ready` (readiness) endpoints.
- Celery application wired to Redis with a `ping` task proving the broker round-trip.
- pytest harness with a PostgreSQL fixture and an honest `requires_db` skip policy.
- `docker-compose.yml`, `backend/Dockerfile`, GitHub Actions CI (lint / test / build).
- ADRs 0001–0007.

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| `alembic upgrade head` succeeds | met | CI `test` job, against `postgres:15` |
| `pytest` passes | met | CI runs the full suite including `requires_db` |
| CI green | met | `lint`, `test`, `build` jobs |
| `docker compose up` starts all services | **not met** | See below |

### Not met: `docker compose up`

Docker is not installed on the development machine (ADR 0005). The compose file and
Dockerfiles are written, `docker compose config` and `docker compose build` run in CI, but
the running stack has never been started. Service startup ordering, healthchecks, and the
API resolving PostgreSQL and Redis by service name are unverified.

This closes when Docker Desktop is installed:

```
wsl --install                      # reboot required
winget install Docker.DockerDesktop
```

## Verified locally

- 39 tests pass, 12 skip. Every skip names the missing `CODESENTINEL_TEST_DATABASE_URL`.
- `ruff check`, `ruff format --check`, `mypy app/` (strict) all clean.
- The migration renders correct PostgreSQL DDL in Alembic offline mode, including the
  hand-written `risk_score DESC NULLS LAST` index and the enum CHECK constraints.

## Deliberately deferred

| Item | Phase | Reference |
|---|---|---|
| Sandbox image and runner | 2 | Blocked on Docker |
| Worker access to the Docker daemon | 2 | ADR 0006 |
| Reading tool versions from the sandbox image | 2/3 | ADR 0003 |
| Scan pipeline tasks; `scans` API routers | 3 | — |
| Frontend | 7 | Anti-pattern #7: API contract must stabilise first |

## Notes for phase 2

Phase 2 cannot begin until a Docker daemon is available. Its first decision is ADR 0006
(how the worker reaches the daemon), which must be resolved before the sandbox runner is
written rather than defaulted into by mounting the socket.
