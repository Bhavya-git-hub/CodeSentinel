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

**All green in CI run 34616216187: 406 passed, 0 skipped, 0 failed, across all four
jobs.** `CODESENTINEL_REQUIRE_INTEGRATION=1` is set, so zero skips means every integration
test actually executed against real PostgreSQL and a real Docker daemon — including the
retention cascade, which is the claim this phase turns on and which could not be
demonstrated locally at all.

Locally: 331 passed, 75 skipped (no Docker, no PostgreSQL on this machine). The gap
between 406 and 331 is the 75, and 19 of them are this phase's own.

| Criterion | Evidence |
|---|---|
| The scan list reports the total, not the page length | `test_the_list_reports_the_total_not_the_page_length` |
| Paging returns every scan exactly once | `test_paging_returns_every_scan_exactly_once` |
| The list is newest first | `test_the_list_is_newest_first` |
| Retention refuses a window of zero | `test_a_retention_of_zero_is_refused_not_treated_as_a_cutoff_of_now` |
| Nothing is scheduled when retention is off | `test_nothing_is_scheduled_when_retention_is_off` |
| A running scan is never pruned, however old | `test_a_running_scan_is_never_pruned_however_old` |
| Pruning frees the repository-scoped tables | `test_a_repository_with_no_scans_left_is_removed_too` |
| A repository keeping one scan keeps its history | `test_a_repository_keeping_one_scan_keeps_its_history` |
| A database outage omits gauges rather than zeroing them | `test_a_database_outage_omits_the_gauges_rather_than_zeroing_them` |
| Request metrics cannot grow an unbounded label set | `test_an_unmatched_path_does_not_create_a_series_per_url` |
| A key name is not a credential | `test_a_name_is_not_a_credential` |
| The derived label is not a piece of the secret | `test_the_derived_label_is_not_a_piece_of_the_secret` |
| A refused credential save is reported as refused | `reports a refused save instead of claiming success` |
| The panel never shows the secret half of a key | `never displays the secret half of a stored key` |
| An unreachable API is not rendered as an empty history | `ScansPage` → `History` renders the error |
| The TLS overlay unpublishes the API and frontend ports | CI step "Validate the TLS overlay" |

One pre-existing warning persists and is not from this phase:
`test_persistence.py::test_repository_url_is_unique` raises
`SAWarning: transaction already deassociated from connection`.

### The defects CI caught

Both were in the new scan-list tests, and neither could have been found locally, because
both tests need PostgreSQL and skip without it.

**1. `owner/project`, not the last path segment.** Two assertions expected
`repository_name_from_url` to return `requests`; it returns `psf/requests`, and its
docstring says so. The production code is right and deliberately so — keeping the owner is
what stops two repositories both called "requests" being indistinguishable in a list,
which is the thing the list exists to prevent. Only the expected strings changed; what
each test is about was left alone, so neither was weakened to make it pass. Two fixtures
carried the same mistake (`demo.ts` said `starlette`, the `ScanHistory` test said
`requests`) and were corrected with it — a fixture showing a shape the API cannot produce
is a fixture lying about itself, which in demo mode is the one thing it must not do.

**2. The ordering test could not have detected a wrong order.** CI returned the list
oldest-first. The endpoint was correct; the test was measuring the harness.

PostgreSQL's `now()` is the **transaction** clock, not the statement clock — it returns
the same instant for every statement in a transaction. This module's session is a single
rolled-back transaction, so three scans POSTed inside it all carried an identical
`started_at`, and their relative order fell through to the `id` tiebreak, which is a
random UUID and says nothing about recency. The test asserted the result of that and
called it an ordering.

This is the more interesting of the two, because it sharpened a claim as well as fixing a
test. The tiebreak buys **determinism, not recency**: scans sharing a timestamp come back
in an arbitrary but *stable* order, which is precisely what paging needs and what
`test_paging_returns_every_scan_exactly_once` covers — that test passed throughout. The
endpoint docstring had said "two scans dispatched in the same transaction can share a
timestamp" without saying why; it now names `now()`'s transaction scope, because that is
the part a reader cannot recover from the code. The test now writes explicit distinct
timestamps, which is what a real deployment produces, since each submission is its own
transaction.

## Running the stack, and the four defects that found

`docker compose up` had never been executed by this project, on any machine, since phase 1
([ADR 0005](../adr/0005-deferred-docker-verification.md)). The development machine still
has no Docker -- no Desktop, no WSL distro, no daemon -- so a `smoke` job was added and the
first run happened on a runner.

**It worked on the fifth attempt.** CI run **34621847390**: the stack comes up, migrates,
reports readiness with both dependencies ok, serves the SPA and the API on one origin, and
scans `pallets/itsdangerous` end to end:

| | |
|---|---|
| Files / commits | 50 / 436 |
| Files ranked | 12 (38 unmeasured -- the non-Python files) |
| Findings | 213: 1 critical, 81 minor, 131 info |
| Dependency edges | 127 |
| Coverage measured | 0 files, correctly -- the sandbox is offline |

Four defects, none of which 406 passing tests, a green four-job CI and eleven prior runs
could reach. Each was invisible to the layer above it.

**1. The clones volume was unwritable, so every scan died before cloning.** Docker seeds an
empty named volume from whatever the image has at the mount point, ownership included --
and the image had nothing there, so the volume came up `root:root` while the container runs
as uid 10001. `mkdtemp` raised EACCES.

**2. Which stranded the scan in RUNNING forever, with `error` NULL.** The worse half, and a
straight C3 violation: a row in RUNNING carries no reason, is indistinguishable from a scan
still working, and is collected by nothing -- the retention pruner skips non-terminal scans
deliberately, so it stays until somebody deletes it by hand.

The line that raised was *already guarded*. `clone_root.mkdir` had been added to defend
against `FileNotFoundError`, under a comment warning that anything escaping there "would
strand the scan in RUNNING forever" -- and the next statement raised `PermissionError`,
which is not `FileNotFoundError` and is not an `IngestionError`, and stranded the scan in
RUNNING forever. Guarding a failure mode one exception type at a time is how that keeps
happening, so the fix closes the class: clone-root setup reports a reason naming the path
and the likely cause, and a catch-all records the reason on the scan row and re-raises.

**3. The socket proxy could not open the socket, and started anyway.**
`/var/run/docker.sock` is `root:docker` mode 660; the proxy runs as uid 10001 and nothing
put it in that group. It served 500 to every request for the life of the deployment.

This is the one DEPLOYMENT.md had flagged since phase 5 as *"untested... that it correctly
relays bytes to a real daemon has not been demonstrated"*, and it is the most instructive
of the four, because **every layer above it behaved correctly**: the worker reported "the
sandbox was unavailable", the pipeline recorded PARTIAL with that reason, the report said
every file was unmeasured. All true. None of it says "the proxy cannot open the socket".
Politeness all the way up produced a deployment that looked like a working system analysing
unremarkable repositories.

It now refuses to start, for the reason ADR 0016 gives for authentication: a deployment
that does not start gets investigated, one that comes up green does not. The check connects
rather than calling `os.access`, because access(2) answers about mode bits and a socket can
look readable and still refuse a connection. It lives in the lifespan rather than in
`create_proxy`, so importing the module does not require a live socket.

**4. The clone root could not be a named volume at all.** With the proxy working, container
creation failed with `bind source path does not exist`. The worker asks the daemon for a
read-only bind mount of the clone; the daemon runs on the host and resolves bind sources
against the *host* filesystem, so a path that exists only inside the worker cannot be
mounted. The clone root is now a bind mount using the same path on both sides.

Rejected: mounting the whole clones volume into the sandbox by name. It works, and it lets
one target's analysis container read every other target's clone. These are arbitrary
repositories chosen by callers, analysed side by side; ADR 0009 does not trade isolation
for convenience.

### The smoke test got it wrong twice, in both directions

Worth recording, because the two mistakes are the subject of this whole project.

**First it was too lax.** It asserted a terminal status and non-zero file and commit
counts -- all of which a totally failed analysis satisfies, because PARTIAL is compatible
with every analyser failing. So it passed a scan with 50 files inventoried, 50 unmeasured
and 0 findings. The acceptance test reproduced, in itself, the exact failure this system is
built to prevent: **a scan that found nothing looking like a scan that found nothing
wrong.**

**Then it was too strict.** Tightened to reject any analyzer status carrying an error, it
went red on the coverage skip -- "the sandbox has no network, so the target's dependencies
were not installed" -- which is the designed, correct outcome. That is the more dangerous
mistake of the two: a red build for the honest result is what pressures the next person
into weakening the skip so CI goes green, turning "could not measure" into "measured
nothing".

It now asserts on the **measurement** (`ranked > 0`, which total failure cannot satisfy)
rather than on the status, and treats only an explicit `failed` as a failure. Reasons print
either way, so a skip is visible without being fatal.

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

- ~~CI must confirm retention.~~ **Done** — run 34616216187, zero skips. Pruning is
  demonstrated to reclaim the repository-scoped tables against a real PostgreSQL.
- ~~The stack has still never been run.~~ **The base stack now runs in CI on every push**
  (run 34621847390). The production and TLS overlays are still only validated, never
  started: two API replicas, two workers, the `!override` port removals and ACME issuance
  remain unexercised, and ACME cannot be exercised anywhere without a real hostname.
- **Stuck scans have no owner.** The pruner deliberately will not collect a RUNNING scan,
  and nothing else does either. The pipeline no longer *creates* them -- an unexpected
  exception now records FAILED with its reason -- but a worker killed mid-scan still leaves
  one behind, and the running-scan gauge is the only thing that would show it. This remains
  the clearest unclaimed problem.
- **`analyzer_statuses` folds every analysis error under the `radon` key.** The real run
  surfaced a coverage skip reported under `radon`, which names the wrong tool. Pre-existing
  since phases 5-8, and cosmetic only in the sense that the reason itself is intact; an
  operator reading the key learns something false about which analyser was involved.
- **API keys are still live secrets in the environment**, unhashed, unrotatable and
  unscoped. ADR 0020 answers "which key was that" and deliberately nothing else.
- **The defect-prediction model still buckets by size**, so the report's top-risk commit
  list is arbitrary within its top bucket. Carried forward unchanged from phases 5–8; a
  finer model remains the honest next step if that list is meant to be read top-down.
- **No scan-duration histogram and no queue-depth gauge.** The two metrics an operator
  would reach for second.
