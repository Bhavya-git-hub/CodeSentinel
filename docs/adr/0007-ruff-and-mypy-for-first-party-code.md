# 0007. Ruff and mypy lint our code; Pylint and Bandit analyse targets

**Status:** accepted — 2026-09-11

## Context

The stack table lists Pylint, Bandit and Semgrep under "static analysis". These are
*product features*: adapters that analyse target repositories. They are not a statement
about how CodeSentinel's own source is linted, and CI needs a linter for our code.

## Decision

Ruff (lint + format) and mypy in strict mode for first-party code, run in CI. Pylint,
Bandit and Semgrep remain target-repository analysers, installed only in the sandbox
image (see ADR 0003). These are separate concerns that happen to share tool names.

Two rule choices are worth recording:

- **`BLE` (flake8-blind-except) is enabled**, which makes anti-pattern #9 -- catching bare
  `Exception` and logging nothing -- a lint failure rather than a review comment. The two
  deliberate broad catches in the readiness probe carry `# noqa: BLE001` with the reason
  they are correct: both report the failure into the response body and the log.
- **`TCH` (flake8-type-checking) is disabled.** SQLAlchemy, FastAPI and Pydantic all
  resolve annotations at runtime. Moving `uuid`, `datetime` or `Settings` into a
  `TYPE_CHECKING` block as `TCH` demands would satisfy the linter and break the ORM.

`disallow_untyped_decorators` is relaxed for `app.workers.*` only: Celery ships no type
information, so `@celery_app.task` is untyped. Scoping the exemption to one package is
narrower than ignoring the module or adopting a third-party stub package for one
decorator.

## Consequences

- Two linting vocabularies in the repository. The distinction is: `backend/pyproject.toml`
  configures *our* code, `sandbox/` configures what runs against *targets*.
- mypy runs over `app/` only. Test code is not type-checked in phase 1.
