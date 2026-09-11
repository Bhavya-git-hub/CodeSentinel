# Phase 3 — Ingestion

## Scope delivered

- `app/services/ingestion/url.py` — URL validation at the API boundary: transport
  allowlist, an unconditional refusal of `ext:`/`ssh`/`git+ssh`/`scp`, and a leading-dash
  check against argument injection.
- `app/services/ingestion/cloner.py` — the hardened clone. Drives its own `Popen` so the
  size guard can actually terminate a running clone, with a timeout, a post-hoc exact
  measurement, `chmod o+rX`, and removal of any partial tree.
- `app/services/ingestion/inventory.py` — the working tree as file records: POSIX path,
  language, lines of code, test/non-test.
- `app/services/ingestion/history.py` — streaming `git log` into commit records with their
  per-file changes.
- `app/services/ingestion/pipeline.py` — orchestration, persistence and the scan
  lifecycle; the only module here that touches the database.
- `app/models/history.py::FileChange` plus migration `0002_add_file_changes`.
- `app/workers/tasks.py` — the Celery entry point, and `build_engine(poolclass=...)`.
- `app/api/v1/scans.py` — `POST /api/v1/scans`, `GET /api/v1/scans/{id}`.
- Settings `clone_allowed_protocols` and `clone_size_check_interval_seconds`, both in the
  reproducibility snapshot.
- A real `git_repo` fixture, and ADRs 0011, 0012, 0013.

Not delivered, as designed: analysers, metrics, findings, dependency graph, scoring, SZZ,
frontend.

## Acceptance

**PENDING — this table must not be filled in until CI has run.** The plan requires the
acceptance evidence to cite a CI run number with its pass/skip counts, and no run exists
for this branch yet.

What is true now, locally:

| Check | Result |
|---|---|
| `ruff check` / `ruff format --check`, backend and sandbox | pass |
| `mypy app/` (strict) | pass, 40 source files |
| `pytest -rs` | **128 passed, 48 skipped** |
| `alembic` revision chain | `0001 → 0002`, single head |

The 48 skips are the whole of the acceptance evidence for this phase, and they are why
the table above is empty:

- **PostgreSQL is absent on this machine.** Everything that proves the pipeline persists
  anything skipped — the full-run test, the FAILED path, the PARTIAL path, the
  `file_changes` round trip, both API integration tests, and every migration test.
- **Docker is absent.** Unchanged from phase 2; C1 remains unverified locally.
- The migration has **not been run in either direction** here. It is hand-written, because
  autogenerate needs a live database to diff against.

`CODESENTINEL_REQUIRE_INTEGRATION=1` converts **46 of the 48** into failures, confirming
they are genuinely gated rather than quietly optional. The remaining two are
`skipif os.name != "posix"` assertions about POSIX mode bits — the world-readable clone,
and the sandbox's refusal of an unreadable tree. They are inapplicable on Windows rather
than unverified, and they run on CI's Linux runners; deliberately, `REQUIRE_INTEGRATION`
does not force those, because failing a test for running on the wrong platform would say
nothing true.

The git fixture is the one integration dependency this machine does have, so the cloner
and history integration tests did run.

## Defects found during the phase

1. **`shutil.rmtree(ignore_errors=True)` silently failed to delete partial clones on
   Windows.** git writes its loose objects and pack files mode `0444` because their
   content is immutable; Windows `unlink` requires the file itself to be writable, so
   `rmtree` raised `PermissionError` and `ignore_errors=True` discarded it. The caller
   then raised *"the partial clone was removed"* about six megabytes still sitting on the
   disk the size guard exists to protect.

   This is the phase's most instructive defect because **CI could not have caught it**:
   POSIX `unlink` checks the parent directory's write bit rather than the file's, so Linux
   deletes the same tree cleanly and the suite stays green forever. It was found only
   because the work happened on Windows. `remove_tree` now clears the read-only bit,
   retries, returns whether the tree is actually gone, and logs `clone.cleanup_failed`
   when it is not — the treatment `runner.py` already gives a container it could not
   remove. Its regression test makes both the file and its parent directory unwritable so
   it fails on either platform.

   The same bug was present in the pipeline's `finally`, where it would have accumulated
   whole clones under `clone_root`, on the failure path where the large ones are.

2. **The PARTIAL path would have raised `MissingGreenlet` on a real database.**
   `_persist_history` rolls back on failure, and a rollback expires every object in the
   session; reading `scan.analyzer_statuses` immediately afterwards is implicit lazy IO,
   which asyncio forbids. Neither planned integration test exercised PARTIAL at all, so it
   would have shipped and first appeared on a real scan. The scan is now refreshed
   explicitly and there is a test.

3. **`clone_root` was assumed to exist.** On a fresh deployment it does not, `mkdtemp`
   raises `FileNotFoundError`, and that is not an `IngestionError` — so it would escape
   the handler and strand the scan in `RUNNING` with no error recorded. The integration
   tests point `clone_root` at `tmp_path`, which always exists, so nothing in the suite
   would have found it.

4. **`mine_history` claimed to stream and did not.** Its docstring argued for streaming on
   six-figure histories while the body called `subprocess.run(capture_output=True)`, which
   reads the whole log into memory first. Replaced with a `Popen` consumed line by line,
   with a test asserting the laziness.

5. **The worker would never have received a task.** `celery_app` did not list
   `app.workers.tasks` in `imports`, so a worker never imports the module,
   `codesentinel.run_scan` is unregistered, and every dispatched scan sits in the queue
   unreceived — with the API returning 202 throughout.

## Deviations from the approved plan

All four are recorded in their commit bodies: the streaming rewrite of `mine_history` and
its `HistoryMiningError`, the three pipeline corrections above, the git fixture docstring
that claimed pinned dates it does not pin, and `HTTP_422_UNPROCESSABLE_CONTENT` in place
of the deprecated `ENTITY` spelling.

## Obligations this places on later phases

- **Phase 4** consumes `loc` and the commit stats. Both are nullable by design; churn
  scoring must treat `None` as unknown rather than coercing it. A fabricated `0` for `loc`
  is either a division by zero or a file of infinite defect density at the top of the risk
  report.
- **Phase 5 must not open the network** to install target dependencies (ADR 0009). It
  pre-populates a read-only wheel cache or marks coverage `skipped` with the reason.
- **`reap_orphans()` must be scoped to the worker's own identity** before concurrent scans
  exist (ADR 0010, carried forward from phase 2). It removes every labelled container,
  including another worker's live ones. Phase 3 introduces a worker but no concurrent
  sandboxes, so it is not reachable yet; phase 5 cannot ship without it.
- **Phase 5 implements the filtering Docker socket proxy** decided in ADR 0013. The
  `Sandbox` service must keep to the narrow set of daemon calls it uses today, or the
  proxy becomes something people widen.
- **Phase 4 onwards may parse target content on the host** under ADR 0011, but may not
  *run* target tooling outside the sandbox.

## Still not met from earlier phases

`docker compose up` remains unverified; Docker is not installed on the development
machine. `docker compose build` passes in CI. This is unchanged from phases 1 and 2.
