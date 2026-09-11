# Phase 9 — production readiness

Scope came from the project's own record of what it had not done: the "Obligations this
leaves" section of [phases 5–8](phases-5-to-8.md), the closing note of
[the frontend sprint](frontend-dashboard.md), and the "What is NOT production-hardened"
list in `docs/DEPLOYMENT.md`. Every item below closes something this repository had
already written down about itself.

## Scope delivered

**The scan list** — `GET /api/v1/scans`, paginated and filterable by status. The frontend
sprint recorded "The API has no scan-list endpoint. `listScans` returns an empty array
rather than inventing one, so the dashboard cannot show scan history yet." It can now.
Ordering carries a tiebreak on `id`, because `started_at` has a server default and two
scans dispatched together can share a timestamp — a sort without one returns a row on two
consecutive pages and never returns another.

**Retention** — `app/services/retention.py`, a `codesentinel.prune_scans` task, and a
`beat` service to run it. Opt-in, default off ([ADR 0019](../adr/0019-retention-is-opt-in-and-deletes-repositories.md)).

**Metrics** — `/metrics`, opt-in and unauthenticated, omitting any gauge it cannot compute
([ADR 0018](../adr/0018-metrics-are-opt-in-and-unauthenticated.md)).

**Named API keys** — `name:secret`, with the name bound into the logging context for the
whole request ([ADR 0020](../adr/0020-api-keys-carry-a-name.md)). Closes the "no audit
trail beyond the request log" consequence ADR 0016 recorded.

**TLS** — `docker-compose.tls.yml` plus `deploy/Caddyfile`
([ADR 0021](../adr/0021-tls-is-a-separate-overlay.md)). Also a worker healthcheck, and an
`/api/` proxy in the frontend's nginx so the non-TLS stack is same-origin too.

**Frontend** — scan history, a Settings page with a credential panel, and the 400px
layout verified at last.

## Acceptance

Locally: **331 passed, 75 skipped** (backend), **58 passed, 0 skipped** (frontend), with
ruff, ruff format, mypy strict, eslint, `tsc --noEmit` and `vite build` all clean.

**The 75 skips are the whole caveat.** Nineteen of them are new: the retention integration
tests, which are the ones that matter most in this phase. What they assert is a foreign-key
cascade — that deleting a repository takes its commits and files with it — and a cascade is
a property of PostgreSQL, not of this code. Locally there is no PostgreSQL and no Docker,
so **retention's central claim is unverified here and CI is the acceptance authority for
it.** The unit tests cover the refusal on `retention_days=0` and the shape of the beat
schedule; they cannot cover the delete.

Equally unverified locally: everything the sandbox tests cover (constraint C1), the scan
list endpoint against a real database, and every compose file — this machine has no
daemon, so the three overlays are checked by CI's `docker compose config` and by nothing
here.

| Criterion | Evidence | Verified where |
|---|---|---|
| The scan list reports the total, not the page length | `test_the_list_reports_the_total_not_the_page_length` | CI (needs PostgreSQL) |
| Paging returns every scan exactly once | `test_paging_returns_every_scan_exactly_once` | CI (needs PostgreSQL) |
| Retention refuses a window of zero | `test_a_retention_of_zero_is_refused_not_treated_as_a_cutoff_of_now` | locally |
| Nothing is scheduled when retention is off | `test_nothing_is_scheduled_when_retention_is_off` | locally |
| A running scan is never pruned | `test_a_running_scan_is_never_pruned_however_old` | CI (needs PostgreSQL) |
| Pruning frees the repository-scoped tables | `test_a_repository_with_no_scans_left_is_removed_too` | CI (needs PostgreSQL) |
| A repository keeping one scan keeps its history | `test_a_repository_keeping_one_scan_keeps_its_history` | CI (needs PostgreSQL) |
| A database outage omits gauges rather than zeroing them | `test_a_database_outage_omits_the_gauges_rather_than_zeroing_them` | locally |
| Request metrics cannot grow an unbounded label set | `test_an_unmatched_path_does_not_create_a_series_per_url` | locally |
| A key name is not a credential | `test_a_name_is_not_a_credential` | locally |
| The derived label is not a piece of the secret | `test_the_derived_label_is_not_a_piece_of_the_secret` | locally |
| A refused credential save is reported as refused | `reports a refused save instead of claiming success` | locally |
| The panel never shows the secret half of a key | `never displays the secret half of a stored key` | locally |
| An unreachable API is not rendered as an empty history | `ScansPage` → `History` renders the error | locally |
| The TLS overlay actually unpublishes the API and frontend ports | CI step "Validate the TLS overlay" | CI (needs Docker) |

## The 400px layout, and the defect it was hiding

The frontend sprint record closed with this, under **NOT verified**: *"Chrome's renderer
stopped responding after a window resize and two subsequent tool calls timed out, so the
phone-width check did not complete. The CSS carries a media query, `overflow-x: auto` on
both wide tables, and `min-width: 0` on grid children, but none of that has been seen
working. It is the first thing to check by hand."*

`resize_window` still does not work here — it reports success and the window does not
change size, which is presumably what stalled it last time. So the check was done a
different way: **the app was loaded into a 400px-wide iframe**, which is a real viewport —
media queries inside an iframe evaluate against the iframe's own width — and measured with
`getBoundingClientRect` across all seven routes. That is better evidence than a screenshot
anyway, because it is a number rather than an impression.

It found a real defect on the landing page.

The existing `@media (max-width: 620px)` narrowed the hero row's tracks to
`minmax(150px, 2fr) 66px 84px 66px`. At a 400px viewport the row lays out 345px wide, and
those tracks plus gaps and padding want about 426. `.hero__queue` has `overflow-x: auto`,
so nothing broke and nothing overflowed the page — **the Risk column simply sat outside the
visible area**, at `right=435` against a 385px limit.

Which is the worst possible column to lose. The hero's entire argument is that every risk
score reads `None`; a visitor on a phone saw File, Churn and Weighting and had to scroll
sideways to find the point the page exists to make. A test could not have caught it — the
page rendered, the data was correct, nothing overflowed — and it would have looked fine to
anyone checking on a laptop.

Fixed with a `@media (max-width: 480px)` block that drops the weighting bar and lays the
row out as File / Churn / Risk. The weighting bar is the column that can go: churn is still
rendered as a measured green figure, so the phosphor still reads as "this was determined",
and the two columns carrying the claim — a real measurement and an admitted unknown — both
survive. The `Bar` is wrapped in `.hero__weight` so the stylesheet has something to key on
rather than an `nth-child` that breaks the next time a column moves.

After the fix, all seven routes at 400px: `scrollWidth - clientWidth == 0` on the document,
no element outside the viewport that is not inside a deliberate horizontal scroller, and
every such scroller itself within the page bounds. The wide tables on `/scans` and
`/scans/<id>` scroll inside their own containers, which is the intended design.

## Decisions worth re-reading

- **A metrics gauge that cannot be computed is absent, not zero.** On a dashboard, zero
  draws a confident flat line along the bottom and absent draws a gap. A flat line at the
  bottom of "scans succeeded" is what a working system looks like just before someone
  concludes nothing is running. Anti-pattern #2 with a graph attached, and a graph is
  harder to argue with than a number.
- **Deleting scans would not have bounded anything.** `file_metrics`, `findings`,
  `dependencies` and `predictions` cascade from `scans`, but `files`, `commits` and
  `file_changes` cascade from `repositories` — and those are the bulk. A pruner that
  deleted only scans would have reported thousands of rows removed and left the database
  growing at exactly the same rate: a job that appears to work.
- **`retention_days=0` is refused, not interpreted.** Zero is the natural spelling of
  "disabled" and also the value for which the cutoff arithmetic yields `now`, selecting
  every scan ever recorded. Those two readings are one typo apart and one of them is
  unrecoverable.
- **The reverse proxy does not inject the API key.** It is three lines, it is what
  `DEPLOYMENT.md` recommends, and turning it on makes *reaching the proxy* the entirety of
  authentication. The directive is in the Caddyfile, commented, under that warning: it is
  correct only once something else decides who may reach the proxy, and the diff that
  enables it looks like a simplification while it is happening.
- **A key's name is not a credential.** The whole configured string is still the secret, so
  sending only the name authenticates nothing and an existing key with no colon keeps
  working. An unnamed key gets `key-<sha256[:8]>` rather than a prefix of itself, because a
  prefix on every log line is a head start shipped to the log aggregator.
- **The frontend nginx grew an `/api/` proxy.** Before it, the bundle's relative request in
  the compose stack landed on the SPA fallback and came back as `index.html` with a 200 —
  surfacing as a JSON parse error rather than "the API is not reachable", which is the
  least informative possible symptom of an ordinary misconfiguration. The upstream is held
  in a variable so nginx resolves it per request; with a literal `proxy_pass`, nginx
  refuses to start on an unresolvable name, turning it into a container that will not boot.

## Obligations this leaves

- **CI must confirm retention.** Nineteen tests skipped here. Until a green run with
  `CODESENTINEL_REQUIRE_INTEGRATION=1`, the claim that pruning reclaims the
  repository-scoped tables is written but not demonstrated.
- **The stack has still never been run.** Three compose files are now validated by CI and
  none has been started. ACME issuance in particular cannot be exercised without a
  hostname that resolves to the host.
- **Stuck scans have no owner.** The pruner deliberately will not collect a RUNNING scan.
  Nothing else does either, so `codesentinel_scans{status="running"}` grows without bound
  where scans die mid-pipeline. This is the clearest unclaimed problem left.
- **API keys are still live secrets in the environment**, unhashed, unrotatable and
  unscoped. ADR 0020 answers "which key was that" and deliberately nothing else.
- **The defect-prediction model still buckets by size**, so the report's top-risk commit
  list is arbitrary within its top bucket. Carried forward unchanged from phases 5–8; a
  finer model remains the honest next step if that list is meant to be read top-down.
- **No scan-duration histogram and no queue-depth gauge.** The two metrics an operator
  would reach for second.
