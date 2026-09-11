# Phase 4 — Risk prioritisation

## Scope delivered

- `app/services/analyzers/radon.py` — the Radon adapter: `cc` and `mi` in the sandbox,
  with a parser that handles Radon's inline per-file `{"error": ...}` form.
- `app/services/mining/churn.py` — recency-weighted churn with a configurable half-life.
- `app/services/scoring/risk.py` — max-normalisation and the risk product, with both
  components preserved.
- `app/services/analyzers/analysis.py` — composes the three, persists `FileMetric` rows.
- Analysis wired into the pipeline **before** the clone is deleted; `classify_outcome`
  extended to account for it.
- `GET /api/v1/scans/{id}/metrics` — the risk-ranked review queue, with an `unmeasured`
  count.
- Settings `churn_half_life_days` and `analysis_enabled`, both in the reproducibility
  snapshot.
- ADR 0014.

Not delivered, as designed: Pylint/Bandit findings, coverage, dependency graph, SZZ,
frontend.

## Acceptance

**PENDING — no CI run exists for this branch.** Acceptance evidence must cite a run number
with its pass/skip counts; this table stays empty until it can.

Locally:

| Check | Result |
|---|---|
| `ruff check` / `ruff format --check`, backend and sandbox | pass |
| `mypy app/` (strict) | pass, 44 source files |
| `pytest -rs` | **158 passed, 54 skipped** |

The six skips added by this phase are the ones that matter most to it:

- **Radon has never been run.** Both `requires_docker` analysis tests skipped. Nothing
  here has demonstrated that Radon is in the image, that it runs under the isolation set,
  or that it emits the JSON shape the parser expects. The parser is thoroughly unit-tested
  against shapes taken from Radon's documented output — which proves the parser is
  self-consistent, **not** that it matches the tool.
- **The metrics endpoint has never touched PostgreSQL.** `DESC NULLS LAST` ordering is
  precisely the kind of thing that works in the ORM and not in the query, and it is
  unverified here.

This is the same position phase 2 was in, and ADR 0014 accepts it: CI is the acceptance
authority for anything behind Docker or PostgreSQL.

## The decision this phase had to make

Radon reads source and imports nothing, so it could legitimately have run on the host
under ADR 0011's "executing target code" line — and that would have made the whole phase
verifiable locally.

It runs in the sandbox anyway. The reasoning is in ADR 0014: the problem is not Radon, it
is that a per-tool exemption becomes the mechanism by which the next tool is judged.
Pylint loads plugins from the target's config; coverage imports the target's code. Each
gets waved through on its own merits by whoever adds it, and the boundary ends up
somewhere nobody chose. Making the rule categorical is what stops that, and the cost is
that this phase cannot prove itself on a laptop.

ADR 0014 also corrects ADR 0013, which put the Docker socket-proxy requirement in phase 5
on the reasoning that phase 3 ran no containers. Analysers are phase 4, so the requirement
arrives a phase earlier than predicted.

## Design choices worth re-reading before phase 5

- **Churn returns three different things.** `0.0` (no changes in the mined history — a
  real measurement), a positive float, and `None` (it changed, but every change was
  binary, so the size is unknown). Collapsing the first and last would rank an actively
  churning binary-heavy file as never-touched.
- **Per-file complexity is the sum of its blocks**, not the mean or max. The mean divides
  out exactly the thing being measured; the max answers a different question that phase 7
  can ask of the raw blocks.
- **Normalisation divides by the maximum**, not min-max. Min-max zeroes the least-complex
  file's risk however hard it churns, and divides by zero when all files are identical.
- **A `None` is never normalised into a `0`.** Doing so would both fabricate a measurement
  and drag the scale, changing every other file's score because of one we failed to
  measure. There is a test pinning this.
- **`risk_score` is `None` when either component is.** Zero is a claim of safety, and an
  unparseable file is the opposite of safe. `NULLS LAST` keeps it out of the top of the
  queue, and the endpoint's `unmeasured` count stops a short queue reading as a clean bill
  of health.

## Obligations this places on later phases

- **Phase 5 is now overdue on two counts**, not upcoming: the filtering Docker socket
  proxy (ADR 0013, phase corrected by 0014), and scoping `reap_orphans()` to the worker's
  own identity before concurrent scans exist (ADR 0010).
- **Phase 5** must not open the network to install target dependencies (ADR 0009), and
  populates `FileMetric.coverage_pct`, still NULL here.
- **Phase 7** should read raw per-block complexity for "the worst function in this file";
  this phase stores only the per-file sum.
- **Any new analyser goes in the image and runs in the sandbox** (ADR 0014). That question
  is closed.

## Still not met from earlier phases

`docker compose up` remains unverified; Docker is not installed on the development
machine. Unchanged since phase 1.
