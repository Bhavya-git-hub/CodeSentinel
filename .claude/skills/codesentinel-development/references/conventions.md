# Code conventions

Contents: [Layout](#layout) · [Module docstrings](#module-docstrings) · [Configuration](#configuration) ·
[Typing](#typing-and-mypy-strict) · [Logging](#logging) · [Errors](#error-design) ·
[ORM](#orm-models) · [Migrations](#migrations) · [Sandbox](#sandbox-code) · [Lint rules](#the-lint-rules-and-why)

## Layout

```
backend/app/
  config.py        Settings — every tunable in the system
  db.py            engine/session factories, all lru_cached and resettable
  logging.py       structlog configuration
  main.py          application factory: create_app(settings)
  api/             routers; api/v1/ for the versioned surface
  models/          SQLAlchemy models, one module per aggregate
  schemas/         Pydantic request/response models
  services/        the actual work, one package per concern
  workers/         Celery app and tasks
sandbox/           the analysis image and its helper scripts (linted too)
```

`services/` packages are already stubbed for the phases that will fill them: `analyzers/`,
`graph/`, `ingestion/`, `mining/`, `prediction/`, `reporting/`, `sandbox/`, `scoring/`. Put
work in the package that owns the concern rather than growing a new top-level one.

A service package that is more than one file splits like `services/sandbox/` does:
`errors.py` (the exception hierarchy), `result.py` (the value objects it returns),
`runner.py` (the machinery). That ordering — failures and results named before the thing
that produces them — keeps the public surface readable.

## Module docstrings

Every module opens with one, and it carries the reasoning rather than a restatement. The
pattern that works: state the constraint the module serves, then the specific trap it is
avoiding.

```python
"""Sandbox failures.

These are distinct from a command failing *inside* the sandbox. A non-zero exit code is
an ordinary result; these exceptions mean the isolation itself could not be established,
which is never something to degrade past (constraint C1).
"""
```

The test for whether a docstring is pulling its weight: would a reader who changes this
code in six months make a mistake without it? If yes, keep it. If it just says
"Configuration for the application", it is costing more than it returns.

The same applies to inline comments. `app/config.py` explains `NoDecode` because the
behaviour it works around (pydantic-settings JSON-decodes list fields inside the env source
before validators run) is invisible and someone would otherwise "simplify" it back into a
bug. That is exactly what a comment is for.

## Configuration

Everything tunable lives on `Settings` in `app/config.py`.

```python
sandbox_timeout_seconds: int = Field(default=600, ge=1)
```

- Env prefix `CODESENTINEL_`, `frozen=True`, `extra="ignore"`, `.env` supported.
- Constrain at the field (`ge=`, `Literal[...]`, `PostgresDsn`) so a bad value fails at
  startup with a clear message rather than deep in a worker.
- Add the variable to `.env.example` under the right section heading, with a comment when
  the value is not self-explanatory.
- Settings for a later phase are defined *now* if they are part of what gets recorded —
  they belong to the reproducibility record (C5), not to the phase that first reads them.
- `Settings.reproducibility_snapshot` is the subset persisted with each scan. If your new
  setting changes what a scan produces, it belongs in that snapshot.
- `get_settings()` is `lru_cache`d; tests clear it via the autouse `_reset_caches` fixture.
  Functions that need settings should **take them as a parameter** (see `build_engine`)
  rather than reaching for the global, so tests and Alembic can supply their own.

## Typing and mypy strict

- `from __future__ import annotations` at the top of every module.
- `mypy` runs `strict` with `warn_unreachable`, plus the pydantic plugin. Untyped defs and
  untyped decorators are errors.
- Relaxations are narrow and justified in `pyproject.toml`: `ignore_missing_imports` for
  `alembic`/`celery`/`docker`, and `disallow_untyped_decorators=False` scoped to
  `app.workers.*` because `@celery_app.task` is untyped. Follow that pattern — scope an
  override to the smallest module set and say why — rather than widening an existing one.
- **The `TCH` ruff rules are deliberately off.** SQLAlchemy, FastAPI and Pydantic resolve
  annotations at runtime, so moving `uuid`, `datetime` or `Settings` into a `TYPE_CHECKING`
  block satisfies a linter and breaks the ORM. Do not "fix" this.
- A `# type: ignore[code]` is always specific and always sits next to a reason.

## Logging

```python
logger = structlog.get_logger(__name__)
logger.warning("sandbox.timeout", run_id=run_id, timeout_seconds=limit)
```

Event names are dotted and stable; the variable parts are keyword fields, not interpolated
into the message. That is what makes a failure reason queryable, which is what C3 is really
asking for. `print` fails lint (`T20`).

## Error design

Model failures as a small hierarchy with a shared base, and put the *reasoning* in each
class's docstring — what it means, and why it is not something to recover from silently.
`app/services/sandbox/errors.py` is the model to copy.

The distinction it draws is the important one: **a failure of the work** (a tool exits
non-zero — an ordinary result, record it) is not **a failure to establish the conditions
for the work** (no daemon, missing image, unreadable source — an exception, refuse).

Refuse rather than repair. When the sandbox found a source tree it could not read, it
raised an error naming the mode and the fix instead of `chmod`-ing the host directory:
silently mutating a caller's filesystem is a surprising side effect, and the obligation
belonged to whatever created the clone. Prefer a loud refusal that names the fix.

## ORM models

- `Base` carries an explicit `NAMING_CONVENTION` so Alembic autogenerates stable, diffable
  constraint names. A later migration that drops a constraint needs a name it can reference.
- `UUIDPrimaryKeyMixin` generates ids in Python, not the database, so a whole object graph
  (scan → files → metrics → findings) can be built in memory and bulk-inserted in one round
  trip.
- `CreatedAtMixin` for server-side, timezone-aware timestamps.
- SQLAlchemy 2.x style throughout: `Mapped[...]` / `mapped_column(...)`.
- **Metric columns are nullable** (ADR 0004). Absent is not zero.
- Enums are stored as VARCHAR with a CHECK constraint, not native PostgreSQL enums
  (ADR 0002), and include explicit members for failed/skipped states so C3's distinction
  survives into the database.

## Migrations

- Alembic, `alembic upgrade head`; `path_separator` is declared explicitly in `alembic.ini`.
- Autogenerate, then **read the generated script** — it is a draft. Check the downgrade
  actually reverses the upgrade; a downgrade test that silently no-ops proves nothing.
- Tests build the schema by running the real migrations, not `metadata.create_all`, so the
  migration scripts themselves are exercised. Keep it that way.

## Sandbox code

Anything touching `app/services/sandbox/` or `sandbox/`:

- Read ADR 0009 (the isolation set) and ADR 0010 (cleanup and timeouts) first.
- The isolation set is applied unconditionally. No parameter relaxes it.
- Containers are removed in a `finally`. `auto_remove=True` races with reading the logs.
- Timeouts **kill** the container; they do not abandon the wait. `container.wait(timeout=)`
  only times out the HTTP request and leaves the container running.
- The container runs as uid/gid 10001 and can only read a world-readable mount.
- Analysis tools (pylint, bandit, semgrep, radon, coverage) are pinned in
  `sandbox/Dockerfile.analysis` and are **not** backend dependencies (ADR 0003). Do not add
  them to `pyproject.toml`.
- `sandbox/` python is linted and formatted by CI like the rest — it is our code.

## The lint rules, and why

`ruff`, line length 100, `target-version = "py311"`. Selected: `E`, `W`, `F`, `I`, `N`,
`UP`, `B`, `C4`, `SIM`, `RUF`, plus two that encode project rules rather than taste:

- **`BLE`** (flake8-blind-except) makes anti-pattern #9 — swallowing an exception — a build
  failure instead of a code-review opinion.
- **`T20`** (flake8-print) forces structured logging.

`tests/*` ignores `S101`; `alembic/versions/*` ignores `E501` and `N999`. Reach for a
per-file ignore before a `noqa`, and a `noqa` before turning a rule off.
