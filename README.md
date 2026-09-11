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

All nine phases delivered. A repository URL submitted to `POST /api/v1/scans` is cloned,
inventoried, mined for history, and analysed inside the sandbox; the result is a
risk-ranked review queue, normalised findings, a coverage read, an import graph, a blast
radius, an SZZ-derived defect-probability pass, and a report that states what it could not
determine.

| | |
|---|---|
| `POST /api/v1/scans` | submit a repository |
| `GET /api/v1/scans` | scan history, newest first |
| `GET /api/v1/scans/{id}` | one scan's state |
| `GET /api/v1/scans/{id}/metrics` | the risk-ranked queue |
| `GET /api/v1/scans/{id}/findings` | Pylint and Bandit, on one severity scale |
| `GET /api/v1/scans/{id}/impact?path=` | what breaks if this file changes |
| `GET /api/v1/scans/{id}/report` | everything, with its own limitations |
| `GET /health`, `/health/ready` | liveness and readiness |
| `GET /metrics` | Prometheus, opt-in and unauthenticated |

A React frontend covers all of it, with measured, genuinely zero and unknown rendered as
three visually distinct states throughout.

Deployment is three compose files — base, production overlay, optional TLS overlay — with
authentication, rate limiting, retention and a filtering Docker socket proxy.
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) ends with a list of what is still **not**
production-hardened, which is the part worth reading first.

**CI runs all three compose files on every push.** The base stack is brought up, migrated,
and used to scan a real repository end to end; the production and TLS overlays are started
together and checked for both API replicas, closed ports, TLS termination and live
authentication. The one thing that has still never run anywhere is public ACME issuance,
which needs a hostname that resolves to the host — use Let's Encrypt staging for the first
deploy. See [ADR 0005](docs/adr/0005-deferred-docker-verification.md) for the deferral this
discharges, and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for what is still not hardened.

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
