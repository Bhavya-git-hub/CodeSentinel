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

Phase 4 (Risk prioritisation) — a repository URL submitted to `POST /api/v1/scans` is
cloned, inventoried, mined for history, measured with Radon in the sandbox, and returned
as a risk-ranked review queue at `GET /api/v1/scans/{id}/metrics`.

Delivered so far: phase 1 foundation (scaffold, configuration, data model, migrations,
health endpoints, test harness, CI), phase 2 sandbox (an isolated, network-less,
resource-bounded analysis container), phase 3 ingestion, phase 4 complexity × churn
prioritisation.

A React frontend now covers the settled contract: a landing page and a risk dashboard
where measured, genuinely zero and unknown are three visually distinct states.

Not yet: Pylint/Bandit findings, coverage, the dependency graph, defect prediction.

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

## Frontend

```
cd frontend
npm install
npm run dev
```

`VITE_CODESENTINEL_DEMO=1 npm run dev` serves bundled fixtures instead of the API and
says so on every page. It is never selected automatically: if the API is unreachable the
UI shows the error rather than quietly substituting sample data.

## Documentation

- Architecture decisions: [docs/adr/](docs/adr/)
- Design specifications: [docs/specs/](docs/specs/)
- Sprint records: [docs/sprints/](docs/sprints/)
