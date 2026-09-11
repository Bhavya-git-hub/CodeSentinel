# Phase 4 — Risk prioritisation: design

**Status:** approved — 2026-09-11

The first phase that produces an *answer* rather than a record. Phase 3 collects what a
repository is and what happened to it; phase 4 turns that into the product's headline
claim: **rank files by `complexity × recency-weighted churn`**, so a reviewer knows what
to read first.

## Scope

Delivered:

- A Radon adapter that measures cyclomatic complexity and maintainability index **inside
  the sandbox** (C1), and parses its JSON into per-file metrics.
- Recency-weighted churn computed from the `file_changes` rows phase 3 captured.
- Normalisation and the risk score, stored with its two components so a rank can be
  explained rather than merely asserted.
- `FileMetric` rows persisted per scan.
- The analysis step wired into the existing pipeline, **before** the clone is deleted.
- `GET /api/v1/scans/{id}/metrics` — the risk-ranked review queue.

Not delivered: Pylint/Bandit findings, coverage, the dependency graph, SZZ, frontend.

## Where the work runs

Radon reads the target's source and imports nothing from it, but it is still a tool
**analysing a target**, and ADR 0011 drew the line at executing target code rather than at
risk assessment per tool. Running analysers on the host would make that line a judgement
call made once per tool, which is how it erodes. So Radon runs in the sandbox, via
`Sandbox.run()`, with no new arguments and no relaxations (ADR 0009).

Churn is computed from **our own database rows**, not from the target, so it runs on the
host. Nothing about a target can influence that computation beyond the numbers phase 3
already recorded.

This means phase 4 is the first phase where **a worker needs a Docker daemon** — which
ADR 0013 said would be phase 5. That is a correction phase 4 has to make, not inherit
silently; see "Deviation from ADR 0013" below.

## Churn

For each file, over its `file_changes` rows:

```
churn = Σ (lines_added + lines_deleted) × 0.5 ^ (age_days / half_life_days)
```

Exponential decay, half-life configurable, `age_days` measured from the scan's start
rather than from "now" so re-reading a stored scan gives the same number it gave when it
ran (C5).

Recency weighting is the whole point. Total lifetime churn ranks a file that was rewritten
five years ago above one being actively churned today, which is precisely backwards for
"what should I review".

**The None rule, which is the load-bearing part:**

| Situation | churn | Why |
|---|---|---|
| File has no `file_changes` rows | `0.0` | A real measurement: it genuinely never changed in the mined history |
| File has rows, all with countable line counts | the sum | |
| File has rows, **every one** binary (`lines_added`/`deleted` all NULL) | `None` | It demonstrably changed; how much is unknown |
| File has a mix | sum of the countable ones | Stated in the report as a partial count |

Collapsing row 1 and row 4 into `0` is anti-pattern #2 and it is not academic: a binary-
heavy file would be reported as never-changing, and would sink to the bottom of the exact
queue it belongs near the top of.

## Complexity

`radon cc -j .` and `radon mi -j .`, both in one sandbox session.

Per-file cyclomatic complexity is the **sum** of its blocks' complexities, not the mean or
the max. A file with forty simple functions offers more places to be wrong than one with
three, and the mean actively hides that by dividing it back out. The max answers a
different question ("where is the worst function") that phase 7's report can ask of the
raw blocks later. The choice correlates with file size, and that is accepted: size is a
real component of review cost.

Maintainability index is clamped to 0–100; Radon's underlying formula can go negative.

Radon reports per-file errors inline (`{"path": {"error": "..."}}`) for a file it cannot
parse — a syntax error, Python 2, a template. Those files get `cyclomatic_complexity =
None` **and the reason recorded**, never 0. A file Radon could not read is not a simple
file, and ranking it as one would hide exactly the kind of file worth looking at.

## Scoring

Both components are normalised to `[0, 1]` by division by the scan's maximum, then
multiplied:

```
normalized_complexity = complexity / max_complexity      (0.0 if max is 0)
normalized_churn      = churn / max_churn                (0.0 if max is 0)
risk_score            = normalized_complexity × normalized_churn
```

Max-normalisation rather than min-max: min-max maps the least-complex file to exactly 0,
which then zeroes its risk product regardless of how much it churns, and it divides by
zero when every file is identical. Dividing by the maximum degrades gracefully in both
cases.

**If either component is `None`, `risk_score` is `None`** — unknown, not zero. The
`ix_file_metrics_scan_id_risk_score` index is already `DESC NULLS LAST`, so an unmeasured
file cannot outrank a measured high-risk one; and the metrics endpoint reports how many
files were unmeasured, so a queue built from half the repository says so.

The score is stored alongside `normalized_complexity` and `normalized_churn` because a
rank nobody can explain is a rank nobody acts on.

## Status semantics

Phase 3's `classify_outcome` grows a second input. Any analyser that fails or is skipped
makes the scan `PARTIAL`, with the reason under its own key in `scans.analyzer_statuses`
(C3). A scan whose complexity could not be measured still has churn, and churn alone is
usable; discarding it would be throwing away work, and calling it `SUCCEEDED` would
present a churn-only ranking as the full risk model.

## Deviation from ADR 0013

ADR 0013 said the phase 3 worker gets no Docker access and phase 5 would implement the
filtering socket proxy, because phase 3 ran no containers. Phase 4 runs containers, so
the need arrives one phase earlier than that ADR predicted. ADR 0014 records the
correction and moves the proxy requirement to phase 4; the decision itself — a filtering
proxy, never a raw socket mount — is unchanged.

## Configuration

| Setting | Purpose |
|---|---|
| `churn_half_life_days` | Decay half-life; default 90. In the reproducibility snapshot — it changes every score |
| `analysis_enabled` | Lets a deployment without a daemon ingest without failing every scan. Recorded in the snapshot, so a scan that skipped analysis says so |

## Testing

Unit, runnable everywhere — this is most of the phase, deliberately, because the maths is
where the wrong answers come from:

- Radon `cc`/`mi` JSON parsing, including the per-file `error` form
- A file Radon failed on yields `None`, not `0`
- Churn decay: a change at exactly one half-life counts half
- Churn is `0.0` for an unchanged file and `None` for an all-binary one
- Normalisation with a zero maximum, and with a single file
- `risk_score` is `None` when either component is

Integration, `requires_docker`: Radon against the real image in the real sandbox.
Integration, `requires_db`: metric persistence and the ranked endpoint.

## Obligations this places on later phases

- **Phase 5** inherits the socket proxy requirement from ADR 0014, and `reap_orphans()`
  must be scoped to the worker before concurrent scans (ADR 0010, still open).
- **Phase 6** consumes `FileMetric.coverage_pct`, still unpopulated here.
- **Phase 7** should read raw per-block complexity for "worst function in the file"; this
  phase stores only the per-file sum.
