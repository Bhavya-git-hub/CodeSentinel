# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this system is, and why it shapes everything

CodeSentinel clones arbitrary public repositories and executes their tooling. Two facts
generate most of the rules below:

1. **It runs other people's code.** A target's `conftest.py` executes at pytest collection
   time; its `setup.py` executes on install. Container isolation is a security boundary,
   not tidiness.
2. **Its entire output is "what is wrong with this code".** A scan that silently finds
   nothing is worse than one that fails loudly — a failure gets investigated, a clean
   report gets trusted and shipped.

## The commands

Run from `backend/`. The interpreter is `.venv/Scripts/python` on Windows,
`.venv/bin/python` on Linux.

```bash
# The gate, in CI's order. Prefer the script -- it is easy to run incompletely.
bash .claude/skills/codesentinel-development/scripts/gate.sh
bash .claude/skills/codesentinel-development/scripts/gate.sh --fast     # no integration
bash .claude/skills/codesentinel-development/scripts/gate.sh --require  # skips become failures

# Or by hand -- note ../sandbox/, which is easy to forget and CI does not:
ruff check . && ruff format --check . && mypy app/
ruff check ../sandbox/ && ruff format --check ../sandbox/
pytest -rs                          # -rs prints the reason for every skip

pytest tests/unit/test_cloner.py::test_the_clone_is_never_shallow -v   # one test
CODESENTINEL_REQUIRE_INTEGRATION=1 pytest -q                           # prove nothing skips
```

Frontend, from `frontend/`:

```bash
npm run lint && npx tsc --noEmit && npm run test -- --run && npm run build
VITE_CODESENTINEL_DEMO=1 npm run dev    # serves bundled fixtures, says so on every page
```

Migrations are never run automatically; see `docs/DEPLOYMENT.md`.

## Reading the gate honestly

**`N passed, M skipped` is not a pass when M > 0.** Say which tests skipped and what
therefore went unverified: *"302 passed, 56 skipped — the sandbox isolation tests did not
run, so constraint C1 is unverified locally."*

This development machine has **no Docker and no PostgreSQL**, so ~56 tests skip by design.
**CI is the acceptance authority** for anything they cover. When work depends on a daemon
or a database, the honest report is "pushed; CI will tell us", not a claim of completion.

CI has repeatedly caught defects no local run could — a source tree the sandbox uid could
not read, UUID keys that did not exist until flush, a coverage analyser with no test
runner in its image. Three more were found only by scanning real repositories, which no
fixture could reach.

## The architecture, in one pass

A scan is dispatched by the API and executed by a Celery worker:

```
POST /api/v1/scans  ->  Scan(PENDING) + task dispatch
  worker: asyncio.run + NullPool engine  ->  pipeline.run_ingestion
    cloner    hardened git clone on the HOST (ADR 0011)
    inventory walk the tree -> File rows
    history   git log -> Commit + FileChange rows
    analysis  Radon / Pylint / Bandit / coverage IN THE SANDBOX (ADR 0014)
              churn + risk scoring on the host (our own rows, not the target)
              import graph via ast.parse on the host (reads bytes, runs nothing)
              SZZ: classify fixes, blame, label, predict
    Scan(SUCCEEDED | PARTIAL | FAILED); clone removed in a `finally`
```

Everything the analysis stage needs must happen **while the clone exists** — the pipeline
deletes it when the scan ends, and there is no second chance.

## Invariants that are not derivable from the code

**Missing data stays missing.** A metric that could not be computed is `None`, never `0`.
A file with no coverage data is not a file at 0% coverage; a file Radon could not parse is
not a file of complexity 0. Columns are nullable by default (ADR 0004); enums carry
explicit `failed` / `skipped` members distinguishable from success. This distinction is
the product's spine — the frontend renders it as three visually distinct states, and
collapsing it anywhere is the single most damaging change you can make.

**Everything that runs target code runs in the sandbox**, without per-tool exemption, even
when a tool plainly does not execute anything (ADR 0014). Reading a target's bytes on the
host is permitted (ADR 0011); running its tooling is not. There is deliberately no
argument to `Sandbox.run()` that relaxes a restriction (ADR 0009).

**Tunables go in `Settings`**, prefixed `CODESENTINEL_`, mirrored into `.env.example`,
never as a constant at a call site. C5 persists the configuration alongside each result,
and a limit hardcoded in a function body cannot be recorded, therefore cannot be
reproduced. Secrets are excluded from `reproducibility_snapshot()` — it is written to
every scan row.

**A test that did not run must never look like one that passed.** Tests reach their
dependencies through `tests/conftest.py` fixtures, which call `_unavailable(reason)` —
skipping with a reason that names what went unverified, or failing outright when
`CODESENTINEL_REQUIRE_INTEGRATION=1`. Never write a bare `pytest.skip`, and never
substitute SQLite for PostgreSQL: the schema uses JSONB, an expression index with
`NULLS LAST`, and asyncpg semantics, so a SQLite run proves nothing while looking green.

**Exceptions are caught narrowly and reported with their reason.** `BLE` is on in ruff; a
genuine broad catch carries `# noqa: BLE001` *and* a comment saying where the reason
surfaces. Log through `structlog`, never `print` (`T20` fails the build).

**Docstrings explain why, not what.** mypy strict already states the types. Spend the
docstring on the reasoning a future reader cannot recover — the race avoided, the
alternative rejected, the constraint being served.

## Shorthand used throughout the code

| Ref | Requirement |
|---|---|
| C1 | All analysis of a target runs inside the sandbox. No host fallback. |
| C2 | Analysis is asynchronous — the API dispatches, a worker runs it. |
| C3 | Failures are recorded with their reason; a report says what it could not determine. |
| C4 | Nothing is fabricated. Unresolvable things are recorded as unresolved, not dropped. |
| C5 | Every result is reproducible: commit SHA, tool versions and config stored with it. |

Anti-patterns cited in code: **#1** a "just for testing" bypass path, **#2** substituting
`0` for missing data, **#7** building UI before the API contract settles, **#9** swallowing
exceptions. Grep before inventing a number you have not seen used.

## Where the reasoning lives

- `docs/adr/README.md` — 17 ADRs. Skim before re-litigating a settled decision.
- `docs/sprints/` — one record per phase: what was accepted, what was deferred, and the
  obligations each phase placed on later ones. Read the most recent before starting work.
- `docs/DEPLOYMENT.md` — deployment, ending with what is **not** production-hardened.
- `.claude/skills/codesentinel-development/` — the full development loop, ORM and
  migration conventions, testing reference, ADR and commit templates. Loads on demand.

## Records and commits

Write an ADR when you make a choice a future reader would second-guess — the signal is
having thought *"the obvious thing here is X, but X is wrong because…"*. Format:
`docs/adr/NNNN-kebab-title.md`, next number, never renumbered, **and add the row to
`docs/adr/README.md`** — an ADR missing from the index is one nobody finds.

Commit subjects are conventional and imperative; **the body is the point**. Say what the
failure mode actually was, what would have looked fine while being broken, and what
breaks if someone undoes it. One commit per idea.
