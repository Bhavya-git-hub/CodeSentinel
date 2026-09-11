# Frontend — landing and risk dashboard

## Scope delivered

- `frontend/` — React 18, TypeScript, Vite. No Tailwind, no component kit, no
  data-fetching library; pinned dependencies.
- A three-module data layer: `api/client.ts` (live), `api/demo.ts` (fixtures),
  `api/source.ts` (selects one, by `VITE_CODESENTINEL_DEMO`, and never falls back).
- `Metric` / `Bar` / `StatusPill` — the primitives that own how an absent value looks.
- `RiskTable` with `sortFiles`, mirroring the database's `DESC NULLS LAST`.
- Landing page, scan submission, scan detail with polling to a terminal status.
- Design tokens, a Dockerfile and nginx SPA config, a compose service, and a CI job.

Not delivered, as designed: findings, coverage, the dependency graph, defect prediction,
authentication, scan history beyond the current browser session.

## Why this was legitimate now

Anti-pattern #7 forbids building UI before the API contract settles. It settled in phases
3 and 4 and was proved by CI run 34587978470, which is what made this work correct to
start rather than premature.

## The concept, and what it is defending

CodeSentinel distinguishes three states most systems collapse into one: **measured**,
**genuinely zero**, and **unknown**. Nullable metrics (ADR 0004), `NULLS LAST` ranking and
the `unmeasured` count in the API contract all exist to keep them apart. A dashboard that
renders `null` as `0`, or as an empty cell, discards five phases of that work at the last
possible moment.

Three rules carry it:

1. **Phosphor encodes measurement, not mood.** Green marks a value the system determined,
   so the amount of green on screen reads as how much of the repository was analysed. It
   is never decoration or a hover colour.
2. **Unknown is slate plus hatch — never amber, never red, never blank.** Amber would mean
   *caution*, a claim about the file we have not earned. Unknown is an absence of signal.
3. **Mono for what the system measured, sans for what we wrote.** The typeface says who is
   speaking.

## Acceptance

All criteria met, in CI run **34594530698**: every job green, including the new
**Frontend** job and **Build images**, which builds the frontend Dockerfile and its nginx
SPA config as part of `docker compose build`.

| Criterion | Evidence |
|---|---|
| The data layer never falls back to fixtures | `never falls back to fixtures when the live client fails` |
| Demo mode cannot be selected by accident | `does not treat an arbitrary value as demo mode` — `"0"`, `"false"` and `""` all select the live API |
| Demo mode is announced whenever fixtures are the source | `announces demo mode when fixtures are the source` |
| `null` renders as `None`, never as `0` or a blank | `renders an unknown value as None, never as zero` |
| A genuine `0` stays distinguishable from an unknown | `distinguishes a zero from an unknown in the DOM`, `draws a measured zero as an empty track, not as hatch` |
| An unmeasured file sorts last, never first | `sorts unknown risk last, never first`, and `keeps unknown last even when every other file scores zero` |
| The queue states what it could not measure | `states how many files could not be ranked`, `says unknown rather than safe` |
| An analyser's reason is surfaced, not hidden | `shows the analyser's reason rather than hiding it` |
| An all-null ranking falls back to churn and admits it | `falls back to churn ordering when nothing could be ranked, and says so` |
| The API's refusal reaches the reader verbatim | `shows the API's own refusal verbatim` — asserts the "Allowed transports" half survives |
| The fixtures do not flatter themselves | `carry a genuinely unknown complexity rather than a flattering number` |

Locally: **26 passed, 0 skipped**; lint, strict `tsc` and `build` all pass. The backend
gate is unchanged at 162 passed, 54 skipped.

**Verified visually:** the landing page and scan detail page were loaded in Chrome against
the dev server in demo mode and read as intended — the hero queue, the phosphor figures,
the slate `None` tokens, and the caveat naming 44 of 44 files unranked.

**NOT verified:** the 400px layout. Chrome's renderer stopped responding after a window
resize and two subsequent tool calls timed out, so the phone-width check did not complete.
The CSS carries a media query, `overflow-x: auto` on both wide tables, and `min-width: 0`
on grid children, but none of that has been seen working. It is the first thing to check
by hand.

## Design decisions worth re-reading

- **`source.ts` has no fallback, deliberately.** A UI that serves fixtures when the API is
  unreachable is a confident report about a repository nobody analysed. Its test asserts
  the *absence* of that behaviour, and is marked not to be deleted to make a "graceful
  degradation" change pass.
- **Demo mode is configuration, not a branch.** Same shape as the backend's
  `clone_allowed_protocols`: explicit, announced by an undismissible banner, unreachable
  by accident (anti-pattern #1).
- **The fixtures tell the truth about themselves.** They carry the figures the real
  services produced against this repository, with `cyclomatic_complexity: null` throughout
  because Radon genuinely could not run without a daemon. Demo mode therefore demonstrates
  the unknown state rather than hiding it behind flattering numbers.
- **When nothing can be ranked, the table falls back to churn ordering and says so.**
  Ranking by an all-null column would produce an arbitrary order that still looks
  authoritative.
- **The browser does not duplicate the backend's URL validation.** A second copy of that
  rule is a second thing to keep in step, and it is the copy an attacker skips. The API's
  refusal is shown verbatim, because "Allowed transports: https" is the half that tells
  the reader what to do.

## Obligations this places on later phases

- **Phase 5** adds findings and coverage. Both carry the same three-state problem and must
  reuse `Metric` / `Bar` rather than inventing a second treatment for absence.
- The landing hero's figures are a committed fixture. When a real deployment exists they
  should come from a live scan; until then they stay labelled as this repository's own
  measurements.
- **The API has no scan-list endpoint.** `listScans` returns an empty array rather than
  inventing one, so the dashboard cannot show scan history yet.
