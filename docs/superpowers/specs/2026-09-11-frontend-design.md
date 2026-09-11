# Frontend: landing and risk dashboard — design

**Status:** approved — 2026-09-11

The first user-facing surface. Phases 1–4 produced a settled, CI-green API contract
(`POST /api/v1/scans`, `GET /api/v1/scans/{id}`, `GET /api/v1/scans/{id}/metrics`), which
is what makes this phase legitimate now and not earlier: anti-pattern #7 forbids building
UI before the API contract settles, and until CI run 34587978470 it had not.

Visual direction is taken from [rubenmarcus.dev](https://www.rubenmarcus.dev/) at the
user's request: green-tinted near-black, phosphor accent, prominent monospace, a
three-role type system.

## The concept

CodeSentinel's data model distinguishes three states that most systems collapse into one:
**measured**, **genuinely zero**, and **unknown**. Five phases of backend work exist to
keep them apart — nullable metrics (ADR 0004), `NULLS LAST` ranking, the `unmeasured`
count in the API contract, `churn = None` for an all-binary history.

A dashboard that renders `null` as `0`, or as an empty cell, throws that away at the last
possible moment. So the distinction is the spine of the design rather than a detail of it.

Three rules follow, and everything else serves them:

1. **Phosphor encodes measurement, not mood.** Green marks a value the system actually
   determined. The quantity of green on screen is therefore a readout of how much of the
   repository was really analysed — a scan where Radon failed looks visibly dim. Green is
   not used decoratively anywhere.
2. **Unknown is slate plus a 45° hatch — never amber, never red, never blank.** Amber
   would mean *caution*, which is a claim about the file. Unknown is an absence of signal
   and must look like one. It is also never visually adjacent to zero.
3. **Mono for what the system measured; sans for what we wrote.** Paths, SHAs, counts,
   scores and the literal token `None` are JetBrains Mono. Prose, labels and navigation
   are Geist. The typeface says who is speaking.

## Tokens

| Token | Value | Role |
|---|---|---|
| `--void` | `#04080A` | page ground |
| `--panel` | `#0A1014` | raised surface |
| `--panel-lift` | `#111A20` | table header, active row |
| `--phosphor` | `#4ADE80` | measured |
| `--phosphor-dim` | `#2A6F4A` | measured, low magnitude |
| `--unknown` | `#6B7A8F` | could not be determined |
| `--halt` | `#E86A5C` | refused or failed |
| `--bone` | `#E8EDF0` | primary text |
| `--mute` | `#8A97A5` | secondary text |
| `--rule` | `#17232B` | hairlines |

Type: **Gabarito** (display) · **Geist** (sans) · **JetBrains Mono** (data). All from
Google Fonts.

Single-theme by deliberate choice: this is an instrument readout, and a light variant
would break rule 1 — phosphor on white does not encode intensity.

## Screens

**Landing (`/`).** The hero is not a statistic with a gradient. The most characteristic
object in this product's world is a ranked queue in which some cells say `None`, so the
hero *is* that queue, rendered with real measured figures from this repository. The thesis
is the artefact. Below it: what complexity × recency-weighted churn means and why either
alone ranks badly; what the honest-reporting rule buys a reviewer.

**Dashboard (`/scans`).** Submit a repository URL; see scans and their status. Validation
errors from the API are shown verbatim — the backend already phrases them for a human
("The transport 'ext' is not permitted. Allowed transports: https."), and paraphrasing
would only lose information.

**Scan detail (`/scans/:id`).** The risk queue. Sortable, with `total_files`,
`unmeasured` and `analyzer_statuses` surfaced as part of the reading, not a footnote. A
scan still running polls until it reaches a terminal status.

## Data layer

Three modules, one rule.

```
src/api/client.ts   real fetch against the API
src/api/demo.ts     fixtures carrying genuine measured numbers
src/api/source.ts   selects one, by VITE_CODESENTINEL_DEMO, at module load
```

**`source.ts` never falls back.** If the live API is unreachable the UI surfaces the
error. It does not quietly serve fixtures, because a frontend that invents data when the
backend is down is precisely the failure mode the backend spends five phases preventing —
a confident report about a repository nobody analysed.

Demo mode is loud: a persistent banner and a badge on every figure. It is configuration,
not a branch inside the client, for the same reason `clone_allowed_protocols` is a setting
rather than a "just for testing" code path (anti-pattern #1).

The fixtures are real: 44 files inventoried under `backend/app`, 39 non-merge commits, the
churn figures actually produced by `churn_score` on this repository's history, and
`complexity: null` throughout — because Radon genuinely could not run without a daemon.
Even the sample data tells the truth about itself.

## Stack

React 18, TypeScript, Vite (port 5173 — already the `cors_origins` default), React Router.
Plain CSS custom properties: no Tailwind, no component kit, no data-fetching library. A
small polling hook covers async scans (C2). Minimal, pinned dependencies, consistent with
ADR 0008.

## Testing

Vitest and Testing Library, with the same house rule as the backend: a test that did not
run must never look like one that passed.

The tests that matter are the ones guarding the concept:

- `null` renders as `None`, never as `0` and never as an empty cell
- a file with `risk_score: null` sorts last, never first
- `source.ts` does not fall back to fixtures when the client throws
- demo mode is visibly announced whenever fixtures are the source
- a genuine `0.0` churn renders differently from an unknown one

## Out of scope

Authentication, multi-user, scan history beyond a list, findings and coverage views
(phase 5 has not produced them), the dependency graph, defect prediction.

## Obligations this places on later work

- **Phase 5** adds findings and coverage. Both carry the same three-state problem, and
  both must use the existing `Measured` / `Unknown` primitives rather than inventing a
  second treatment.
- The landing hero's figures are a committed fixture. When a real deployment exists it
  should be replaced with a live scan, and until then it stays labelled as this
  repository's own measurements.
