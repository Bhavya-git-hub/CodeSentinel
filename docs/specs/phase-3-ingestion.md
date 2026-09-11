# Phase 3 — Ingestion: design

**Status:** approved — 2026-09-11

The first phase in which CodeSentinel does something end to end. A caller submits a public
repository URL and gets back a scan id; a worker clones the repository, inventories its
files, mines its commit history, and records the result. No analysers run yet — phases 4
onward fill in what is measured. What phase 3 must get right is the *path*: the clone is
the first moment untrusted input reaches this system, and every later phase reads what
ingestion writes.

## Scope

Delivered:

- A hardened clone of a public repository, size- and time-bounded, full history, left
  world-readable for the phase 2 sandbox.
- A file inventory: path, language, lines of code, test/non-test classification.
- Commit history: non-merge commits with author, timestamp, summary and change stats.
- A new `file_changes` table linking commits to the individual files they touched, and
  the model and migration that introduce it.
- Scan lifecycle orchestration in a Celery task, with the C5 reproducibility snapshot
  taken at dispatch.
- `POST /api/v1/scans` and `GET /api/v1/scans/{id}`.

Not delivered: analysers, metrics, findings, dependency graph, scoring, SZZ. No frontend
(anti-pattern #7 — the API contract stabilises first).

## Architecture

```
POST /api/v1/scans {url}
  -> validate URL, upsert Repository, insert Scan(PENDING, config=snapshot)
  -> dispatch run_scan(scan_id), return 202 + scan id
        |  Celery worker
  asyncio.run -> engine(NullPool) -> pipeline.run_ingestion(scan_id)
        |
  cloner.clone_repository()    -> CloneResult(path, commit_sha, default_branch)
  inventory.inventory_files()  -> FileRecord[]
  history.mine_history()       -> CommitRecord[]
        |
  persist; Scan(SUCCEEDED | PARTIAL | FAILED + error); clone removed in `finally`
GET /api/v1/scans/{id} -> status, commit_sha, counts, error
```

Each service is independently testable and knows nothing about its neighbours. The
pipeline composes them and owns the database and the scan's lifecycle; the services
themselves perform no I/O against the database.

### Modules

| Module | Responsibility |
|---|---|
| `app/services/ingestion/errors.py` | The ingestion exception hierarchy |
| `app/services/ingestion/cloner.py` | Hardened clone, size guard, timeout, world-readable result |
| `app/services/ingestion/inventory.py` | Walk the tree, classify files, count lines |
| `app/services/ingestion/history.py` | `git log` to commit records |
| `app/services/ingestion/pipeline.py` | Orchestration, persistence, scan lifecycle |
| `app/workers/tasks.py` | Celery entry point |
| `app/api/v1/scans.py` | The two endpoints |
| `app/schemas/scan.py` | Request and response models |

## The cloner

This is the security-critical component: it is where a hostile URL meets a real process.

### Why not `Repo.clone_from`

The obvious implementation — a `RemoteProgress` subclass that raises once the destination
exceeds the budget — **cannot abort a clone**. GitPython dispatches progress from daemon
pump threads in `handle_process_output` which catch handler exceptions and re-raise them
into the dying pump thread, not into the caller. `git clone` keeps running and keeps
filling the disk, while a `pytest.raises` test passes. This was verified against the
installed GitPython source by two independent implementations before this design was
written.

So the cloner drives `Git().clone(..., as_process=True)` and owns the `Popen` itself.

Driving the process directly bypasses `clone_from`'s `check_unsafe_protocols` screen, so
that check is **re-applied explicitly**. Without it an `ext::` URL is arbitrary command
execution on the host.

### The hardening set

Applied unconditionally, in the spirit of ADR 0009 — no argument weakens it.

| Control | What it stops |
|---|---|
| `protocol.allow=never` plus an explicit allowlist | `ext::` command execution and every exotic transport |
| `--no-recurse-submodules` | Pulling further untrusted content outside the size budget |
| `core.hooksPath` pointed at an empty directory | A repository's hooks executing during clone |
| `GIT_TERMINAL_PROMPT=0`, empty `core.askPass` | Hanging forever on a credential prompt |
| `core.symlinks=false` | Symlinks escaping the clone root |
| Size sampling, then `terminate` -> `kill` -> `wait` | Filling the disk; the partial tree is deleted |
| `clone_timeout_seconds` on the same wait | A stalled remote hanging the worker indefinitely |
| `chmod o+rX` on success | The sandbox being unable to read the clone |

The clone is **full, never shallow**. Phase 4 churn and phase 8 SZZ both need the complete
commit graph; the size guard replaces the bound a `--depth` limit would have given.

### The world-readable obligation

Phase 2 recorded this as a requirement on phase 3, and it is the highest-consequence line
in the phase. The sandbox runs as uid 10001, which never matches the host user that made
the clone. A clone that is not world-readable is invisible inside the container: every
analyser sees an empty workspace, finds nothing, and the scan looks healthy — a clean
report for a repository nobody analysed. The cloner applies `o+rX` and the sandbox still
refuses anything it cannot read, so the guarantee is asserted at both ends.

### Size guard semantics

The guard samples the destination directory's size on an interval. It is a **ceiling with
overshoot, not a hard cap**: between two samples a fast transfer can add a large amount,
so the bound is `limit + (interval x transfer rate)`. An exact re-measurement runs after
the process exits, and a clone that exceeded the limit is deleted either way. The
interval is a setting so the overshoot is tunable rather than implicit.

## Inventory

Walks the working tree, skipping `.git` and not following symlinks.

Per file: repository-relative POSIX path, language by extension, lines of code, and a
test/non-test flag (`tests/` directories, `test_*.py`, `*_test.py`, `conftest.py`).

**Undecodable or binary files get `loc = None`, never 0.** Zero lines is a real
measurement about a real empty file; `None` means "we could not count". Collapsing the two
is anti-pattern #2 and would feed phase 4's risk scoring a fabricated value.

## History

`git log` over non-merge commits — the `commits` table is defined as non-merge, because a
merge's diffstat double-counts the changes already attributed to its parents, which would
inflate phase 4 churn.

Per commit: sha, author email, timezone-aware authored timestamp, message summary, and
files-changed / lines-added / lines-deleted. Where a stat cannot be computed it is `None`,
not 0, for the same reason as `loc`.

Commits are processed and persisted in batches rather than accumulated in memory: a large
target can carry six figures of commits, and the object graph is built for bulk insert
(which is why `UUIDPrimaryKeyMixin` generates ids in Python).

### The `file_changes` table

The data model as delivered by phase 1 records only *aggregate* per-commit stats. Nothing
links a commit to the individual files it touched, and phase 4's headline capability —
`complexity x recency-weighted churn` — is computed **per file**.

This has to be resolved in phase 3 rather than phase 4, because **the clone is deleted
when the scan ends**. The commit-to-file mapping exists only while the repository is on
disk; a phase 4 that needs it and does not have it must clone the repository a second
time. Extracting it during the single walk ingestion already performs is close to free.

```
file_changes
  commit_id      -> commits.id      (cascade delete)
  file_id        -> files.id, NULLABLE
  path           the path AT that commit
  lines_added    int | None
  lines_deleted  int | None
  change_type    added | modified | deleted | renamed
```

`file_id` is nullable and `path` is stored alongside it because a file touched in history
may not exist at HEAD — it was deleted, or renamed, and so has no row in `files`. Dropping
those rows would silently understate churn on exactly the files that churned most. This is
the same shape as `dependencies.target_file_id` / `raw_module_name`, and for the same
reason (C4: record the unresolvable rather than discarding it).

Binary files report `-` for their line counts in `git log --numstat`; those become `None`,
not 0.

## Configuration

New settings on `Settings`, all `CODESENTINEL_`-prefixed and mirrored into `.env.example`:

| Setting | Purpose |
|---|---|
| `clone_allowed_protocols` | Transport allowlist, default `["https"]` |
| `clone_size_check_interval_seconds` | Size-guard sampling interval; sets the overshoot bound |

`max_repo_size_mb`, `clone_timeout_seconds` and `clone_root` already exist and are used as
defined. `clone_size_check_interval_seconds` joins `reproducibility_snapshot()` because it
changes the effective size ceiling, and therefore what a scan accepted.

### The test seam, and why it is configuration rather than a bypass

Tests must clone something, and the hardening blocks `file://`. The tempting answer is a
"just for testing" code path, which is anti-pattern #1 — a bypass that exists in
production because it existed in a test.

Instead the transport allowlist is an ordinary setting. Tests set
`clone_allowed_protocols=["file"]`; production defaults to `["https"]`. There is no branch
in the cloner that asks whether it is under test, the weaker configuration cannot be
reached without being set explicitly, and because the value is in the reproducibility
snapshot, a scan that ran under a relaxed allowlist says so in its own record.

## Status semantics

| Status | When |
|---|---|
| `PENDING` | Row inserted, task not yet started |
| `RUNNING` | Worker picked it up |
| `SUCCEEDED` | Clone, inventory and history all complete |
| `PARTIAL` | Clone and inventory complete, history mining incomplete |
| `FAILED` | Clone refused, failed, or timed out; nothing usable produced |

`PARTIAL` is recorded with an `"ingestion"` key in `scans.analyzer_statuses`, carrying the
reason, so the scan remains self-describing per C3. A repository whose files were
inventoried but whose history could not be fully mined still supports phase 6's dependency
graph; discarding it as `FAILED` would throw away usable work, and reporting it as
`SUCCEEDED` would let phase 4 compute churn over a truncated history and present the
result as complete.

`scans.error` always names the cause in terms a reader can act on — never a bare exception
string (anti-pattern #9).

## Error design

```
IngestionError
├── UnsafeRepositoryUrlError   rejected before any process starts
├── RepositoryTooLargeError    exceeded the size budget; partial clone deleted
├── CloneTimeoutError          exceeded clone_timeout_seconds; process killed
└── CloneFailedError           git exited non-zero; stderr summarised
```

The distinction phase 2 drew applies here too: a target that is genuinely too large is an
ordinary, recordable outcome of the work, not a system fault. Each error carries the fact
the operator needs — the limit, the measured size, the timeout, the exit status — because
an error that only says "clone failed" costs someone a reproduction.

## Worker and database

Celery tasks are synchronous; the data layer is `asyncio` throughout. The entry point
wraps an async body in `asyncio.run()` and builds a fresh engine with `NullPool` for that
loop.

This keeps one driver and one session idiom in the codebase. The alternative — adding
`psycopg` and a synchronous `Session` for workers — means every query can be written two
ways and the two must be kept in step forever. The cost is an engine per task, which is
negligible beside a clone.

`NullPool` is required rather than preferred: a pooled asyncpg connection created in one
event loop and reused in another raises "attached to a different loop". `tests/conftest.py`
already encodes this lesson for the same reason.

## API

```
POST /api/v1/scans
  body     {"url": "https://github.com/owner/name"}
  202      {"scan_id": "...", "status": "pending"}
  422      invalid or disallowed URL

GET /api/v1/scans/{scan_id}
  200      {"scan_id", "status", "commit_sha", "error",
            "file_count", "commit_count", "started_at", "completed_at"}
  404      unknown scan
```

URL validation happens at the API boundary so an unusable URL is rejected synchronously,
with a message, rather than becoming a `FAILED` scan the caller has to poll for.

## Testing

Unit, runnable everywhere:

- URL validation: accepted forms, and each rejected transport including `ext::`
- Language and `is_test` classification across representative paths
- `loc` on undecodable bytes yields `None`, and on a genuinely empty file yields `0`
- Size guard terminates a stub process once the budget is exceeded, and removes the tree
- Commit record mapping, including absent stats becoming `None`
- Scan status transitions driven through the pipeline with the services stubbed

Integration, `requires_db`:

- The full pipeline against a real git fixture repository, persisted and read back
- A repository that exceeds the size budget is recorded `FAILED` with the limit named
- The clone is world-readable after a successful run

The git fixture repository is built by a new `conftest.py` fixture — placed alongside the
existing fixtures, not privately in a test module, so it is reused rather than
reinvented. The git binary dependency routes through `_unavailable()`, so a machine
without git skips with a reason saying what went unverified, and CI, which sets
`CODESENTINEL_REQUIRE_INTEGRATION=1`, fails instead.

## ADRs this phase produces

| ADR | Decision |
|---|---|
| 0011 | Cloning is hardened on the host; the C1 boundary is executing target code, not reading its bytes |
| 0012 | Workers run an async body per task under `asyncio.run` with `NullPool`, rather than adding a sync driver |
| 0013 | Resolves ADR 0006: phase 3 needs no Docker, so the worker gets no daemon access; the mechanism is chosen now and implemented in phase 5 |

## Obligations this places on later phases

- **Phase 5** must not open the network to install target dependencies (ADR 0009 stands).
- **`reap_orphans()` still needs scoping** to the worker's own identity before concurrent
  scans exist (ADR 0010). Phase 3 introduces the worker but not yet concurrent sandboxes;
  phase 5 cannot ship without this.
- **Phase 4** consumes `loc` and the commit stats. Both are nullable by design; churn
  scoring must treat `None` as unknown rather than coercing it.
