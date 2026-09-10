# CodeSentinel

Code review and quality intelligence platform.

CodeSentinel ingests a public Python repository **together with its commit history** and
produces a prioritised, risk-ranked quality assessment. Static analysis alone tells you
*what is wrong*; correlating static analysis with version-control history tells you
*what to fix first, and what breaks if you do*.

## Capabilities

1. **Risk-based prioritisation** — rank files by `complexity x recency-weighted churn`.
2. **Change impact / blast radius** — AST-derived dependency graph.
3. **High-risk untested code** — coverage intersected with complexity and churn.
4. **Defect-prone commit prediction** — simplified SZZ over the repo's own bug-fix history.

## Status

Phase 1 (Foundation) — scaffold, configuration, data model, migrations, health endpoints,
test harness, CI. No analysers, sandbox, or ingestion yet.

## Development

```
cd backend
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

Tests that need PostgreSQL are marked `requires_db` and skip with an explicit reason when
`CODESENTINEL_TEST_DATABASE_URL` is unset or unreachable. They are never silently passed,
and SQLite is never substituted.

## Documentation

- Architecture decisions: [docs/adr/](docs/adr/)
