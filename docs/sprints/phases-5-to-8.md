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

All green in CI run **34597351323**: **283 passed, 0 skipped, 0 failed**, across all four
jobs. `CODESENTINEL_REQUIRE_INTEGRATION=1` is set, so zero skips means every integration
test executed against real PostgreSQL and a real Docker daemon — including, for the first
time, Pylint, Bandit and coverage running inside the built analysis image.

Locally: 227 passed, 56 skipped (no Docker, no PostgreSQL on this machine).

### The defect CI caught

**Coverage could never have run.** It drives the target's suite with
`coverage run -m pytest`, and pytest was not in the analysis image — only pylint, bandit,
semgrep, radon and coverage were. That command failed with `ModuleNotFoundError` for every
target, always.

What makes it the worst kind of bug is the error it produced: *"the sandbox has no
network, so the target's dependencies were not installed"*. That reason is true of many
repositories and entirely plausible, so a reader would have concluded the offline
constraint was biting while the real limit — a missing test runner — stayed invisible
behind a correct-sounding explanation. An analyser that fails for a reason nobody
questions is worse than one that fails loudly.

pytest is now pinned in the image and listed in the version manifest, because coverage's
result depends on the runner as much as on coverage itself (C5).

The failing test had asserted a full ingestion run reaches `SUCCEEDED`. It now reaches
`PARTIAL` correctly, since coverage genuinely cannot run against a two-file fixture with
no installable dependencies. The assertion was relaxed to "terminal, not FAILED" — which
is what that test is actually about — and tightened in the same edit: a `PARTIAL` scan
must now carry a recorded reason, so the relaxation cannot hide an analyser failing
silently.

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
- ~~The SZZ pass is not yet wired into the pipeline.~~ **Done.** `blame.py`, `model.py`
  and `pass_.py` complete it: the pass labels commits, blames the lines each fix repaired,
  writes `is_bugfix` / `is_defect_inducing`, and produces `Prediction` rows. Exposed in the
  report as `commits_labelled`, `commits_defect_inducing` and `top_defect_risks`.
- **The frontend covers only the risk queue.** Findings, impact and report endpoints have
  no UI.
