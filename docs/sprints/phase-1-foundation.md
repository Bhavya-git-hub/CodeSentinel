# Phase 1 â€” Foundation

## Scope delivered

- Project scaffold per section 4 of the brief; packages for later phases created empty.
- `pydantic-settings` configuration with a `reproducibility_snapshot()` for constraint C5.
- Full data model: all eight tables at the scan/commit/file grain, SQLAlchemy 2.x async.
- Alembic async environment and a hand-reviewed initial migration.
- `/health` (liveness) and `/health/ready` (readiness) endpoints.
- Celery application wired to Redis with a `ping` task proving the broker round-trip.
- pytest harness with a PostgreSQL fixture and an honest `requires_db` skip policy.
- `docker-compose.yml`, `backend/Dockerfile`, GitHub Actions CI (lint / test / build).
- ADRs 0001â€“0007.

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| `alembic upgrade head` succeeds | met | CI `test` job, against `postgres:15` |
| `pytest` passes | met | 53 passed, **0 skipped** in CI — every `requires_db` test ran |
| CI green | met | `lint`, `test`, `build` all green (run 34522884899) |
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

- 41 tests pass, 12 skip. Every skip names the missing `CODESENTINEL_TEST_DATABASE_URL`.
- `ruff check`, `ruff format --check`, `mypy app/` (strict) all clean.
- The migration renders correct PostgreSQL DDL in Alembic offline mode, including the
  hand-written `risk_score DESC NULLS LAST` index and the enum CHECK constraints.

## Defects CI caught that local runs could not

Worth recording, because each one supports keeping the database tests mandatory in CI
rather than treating a green local run as sufficient:

1. **`--require-hashes=false`** — a boolean pip flag given a value. Broke the image build.
2. **Windows-generated lock file** — pinned `pywin32` (no Linux distribution) and *omitted*
   `uvloop`/`httptools`. The first failed loudly; the second would have silently shipped
   uvicorn without its event loop. Led to ADR 0008.
3. **Alembic `path_separator`** — a real deprecation, promoted to an error by the suite's
   `filterwarnings`, which broke every `requires_db` test at fixture setup.
4. **Environment-coupled tests** — three tests asserted properties of the machine
   (`environment == "local"`, dependencies being down) rather than of the code, and
   inverted in CI where the services are up.
5. **`command.upgrade(cfg, "base")` is a no-op**, not a downgrade. The downgrade test had
   been asserting against a schema that was never reversed.
6. **Cross-loop connection reuse** — a session-scoped pooled engine handing asyncpg
   connections to function-scoped event loops. Fixed with `NullPool`.

Items 5 and 6 were only reachable once the database tests actually executed. The
"fail if database tests were skipped" CI step exists so that can never quietly stop
happening.

## Deliberately deferred

| Item | Phase | Reference |
|---|---|---|
| Sandbox image and runner | 2 | Blocked on Docker |
| Worker access to the Docker daemon | 2 | ADR 0006 |
| Reading tool versions from the sandbox image | 2/3 | ADR 0003 |
| Scan pipeline tasks; `scans` API routers | 3 | â€” |
| Frontend | 7 | Anti-pattern #7: API contract must stabilise first |

## Notes for phase 2

Phase 2 cannot begin until a Docker daemon is available. Its first decision is ADR 0006
(how the worker reaches the daemon), which must be resolved before the sandbox runner is
written rather than defaulted into by mounting the socket.
