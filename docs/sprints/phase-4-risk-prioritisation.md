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

All criteria met, in CI run **34587978470**: **216 tests passed, 0 skipped, 0 failed**.

The `requires_docker` tests in this phase are the whole of its acceptance evidence, and
they ran: `CODESENTINEL_REQUIRE_INTEGRATION=1` would have failed the build had the daemon
or the image been missing.

| Criterion | Evidence |
|---|---|
| Radon actually runs inside the sandbox | `test_radon_measures_complexity_inside_the_sandbox` — measured against the real `codesentinel/analysis:ci` image under the full isolation set |
| A branching function measures more complex than a straight-line one | Same test: `branchy.py` > `simple.py`, so the numbers mean what they claim |
| A file Radon cannot parse is unknown, not simple | `test_an_unparseable_file_is_reported_as_unknown_not_as_simple` — absent from `values`, present in `errors` |
| Churn decays: one half-life counts half | `test_a_change_one_half_life_old_counts_half` |
| Recent churn outranks larger old churn | `test_recent_churn_outranks_larger_old_churn` |
| An unchanged file scores 0.0; an all-binary history scores None | `test_a_file_that_never_changed_scores_zero`, `test_an_all_binary_history_is_unknown_not_zero` |
| An unknown component yields an unknown risk, not a zero one | `test_an_unmeasured_complexity_yields_an_unknown_risk_not_a_zero_one` |
| A `None` does not shift the normalisation scale | `test_unmeasured_files_do_not_shift_the_normalization_scale` |
| The queue ranks by risk, descending | `test_files_are_ranked_by_risk_descending` — against real PostgreSQL |
| An unmeasured file sorts last, not first | `test_an_unmeasured_file_sorts_last_rather_than_first` — `DESC NULLS LAST` verified in the query, not merely declared in the ORM |
| The queue reports what it could not measure | `test_the_queue_reports_how_much_it_could_not_measure` |

The previous revision of this file said Radon had never been executed. It has now.

Locally the same suite reports 162 passed and 54 skipped, because this machine has neither
Docker nor PostgreSQL. That remains the correct local result, and CI remains the authority.

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
