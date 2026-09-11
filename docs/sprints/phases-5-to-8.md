# Phases 5–8 — findings, graph, report, prediction

Delivered in one pass at the user's request ("build the complete project"). Each phase
keeps its own scope; this record covers all four because they shipped together.

## Scope delivered

**Phase 5 — findings and coverage**
- `analyzers/findings.py` — Pylint and Bandit adapters, severity normalised at the
  boundary, exit-status semantics handled per tool.
- `analyzers/coverage.py` — the target's suite run under coverage inside the sandbox,
  offline, recording SKIPPED with a reason when it cannot run.
- The two overdue obligations: `reap_orphans()` scoped to one worker, and the Docker
  socket proxy (ADR 0015).
- `GET /api/v1/scans/{id}/findings`.

**Phase 6 — dependency graph**
- `graph/imports.py` — AST import extraction, module index, blast radius.
- Edges persisted with unresolved ones kept and explained.
- `GET /api/v1/scans/{id}/impact?path=…`.

**Phase 7 — report**
- `GET /api/v1/scans/{id}/report` — the ranking, findings, graph and coverage assembled
  with a `limitations` list stating what the scan could not determine.

**Phase 8 — defect prediction**
- `prediction/szz.py` — conservative bug-fix classification and blame-based labelling.

## Acceptance

**PENDING — no CI run for this work yet.**

Locally: **227 passed, 56 skipped**; ruff, ruff format, mypy strict all pass.

The 56 skips are the usual: no PostgreSQL and no Docker on this machine. That matters
more here than in earlier phases, because **none of the new analysers has ever been
executed**. Pylint, Bandit and coverage have unit-tested adapters and untested
invocations; the integration tests that would run them against the real image are among
the skipped. CI is the acceptance authority and has not yet been asked.

## The decisions worth re-reading

- **A linter exiting non-zero is a result, not a failure.** Pylint encodes what it found
  in an exit bitmask (2 error, 4 warning, 8 refactor, 16 convention); Bandit exits 1 when
  it finds something. Reading either as a tool failure discards every useful run and
  reports PARTIAL with no findings.
- **Coverage may not open the network.** Installing a hostile repository's declared
  dependencies would be executing attacker-chosen package code with network access. So
  coverage runs against what the image provides or records SKIPPED — and the reason names
  the offline constraint, so a reader does not conclude the target is broken.
- **`coverage_pct` stays NULL for unmeasured files.** A file the suite never reached is
  not a file at 0%.
- **Unresolved import edges are kept with their reason.** A blast radius that omits edges
  understates itself, and an understated blast radius is how a change ships believing it
  is safe. The impact endpoint returns `unresolved_edges` so the number reads as a floor.
- **SZZ refuses to guess.** Unlabelled is not negative: a commit with no message is
  undecided, not "not a bug fix". The bug-fix vocabulary uses word boundaries because
  matching `fix` as a substring catches *prefix*, *suffix* and *fixture*, and every false
  positive becomes a fabricated defect-inducing label. Blame only suspects commits that
  predate the fix, and a blamed sha with no known date is skipped rather than assumed
  older.
- **ADR 0015 corrects ADR 0013.** An endpoint socket proxy cannot refuse privileged flags
  or host bind mounts, because those live in the body of a request it must allow. What it
  does and does not stop is now written down, and body-level filtering is recorded as owed.

## Obligations this leaves

- **Body-level filtering of `POST /containers/create`** (ADR 0015). Until it exists, the
  worker's integrity is a security boundary, tolerable only because the worker never
  executes target code (ADR 0011).
- **The SZZ pass is not yet wired into the pipeline.** `szz.py` provides the labelling
  primitives and they are tested; running them over a scan's history, and persisting
  `is_bugfix` / `is_defect_inducing`, is not done. The columns stay NULL, which is the
  correct representation of "the pass has not run" — but no scan currently populates them.
- **No `Prediction` rows are produced.** The table and model exist from phase 1; nothing
  writes to them.
- **The frontend covers only the risk queue.** Findings, impact and report endpoints have
  no UI.
