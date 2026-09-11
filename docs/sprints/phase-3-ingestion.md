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

All criteria met, in CI run **34587978470**: **216 tests passed, 0 skipped, 0 failed**.

Zero skipped is the number that matters. CI sets `CODESENTINEL_REQUIRE_INTEGRATION=1`, so
an unavailable dependency fails the build rather than quietly removing the test — every
row below was actually executed against real PostgreSQL and a real Docker daemon.

| Criterion | Evidence |
|---|---|
| A public repository is cloned with its full history | `test_a_repository_is_cloned_with_its_full_history` — 40-char SHA, working tree present, and all three fixture commits reachable, so the clone is not shallow |
| An oversized repository is refused and leaves nothing behind | `test_an_oversized_repository_is_refused_and_removed` — the error names the 1 MB limit and the destination no longer exists |
| A disallowed transport never starts a process | `test_a_disallowed_transport_never_starts_a_process` — `ext::` refused, no destination created |
| The clone is readable by the sandbox uid | `test_the_clone_is_world_readable` — ran on CI's Linux runner, where the mode bits mean something |
| History is mined newest-first with per-file changes | `test_every_commit_is_mined_newest_first`, `test_commits_carry_their_per_file_changes` |
| An unreadable history is distinguishable from an empty one | `test_a_failing_git_log_raises_rather_than_yielding_nothing` |
| The pipeline persists files, commits and file changes | `test_a_full_run_records_files_commits_and_changes` |
| A failed scan records why | `test_an_unreachable_repository_is_recorded_as_failed` |
| Incomplete history is PARTIAL and self-describing | `test_unminable_history_is_partial_and_says_so` |
| The clone does not outlive the scan | `test_the_clone_is_removed_whatever_happens` |
| The migration runs both directions and matches the models | `test_upgrade_head_creates_every_table`, `test_migration_matches_the_models`, `test_downgrade_removes_every_table` |
| `file_changes.file_id` is genuinely nullable in the database | `test_a_file_change_persists_without_a_file_row` |

Locally the same suite reports 162 passed and 54 skipped: this development machine has no
Docker and no PostgreSQL. Local green was never sufficient, and the section below is why.

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

6. **UUID primary keys did not exist until flush — found by CI, and the worst defect of
   the phase.** `UUIDPrimaryKeyMixin` documented its reason for existing as letting a
   full object graph be built in memory and bulk-inserted in one round trip. It did not
   do that: `default=uuid.uuid4` is a *Core* column default evaluated during INSERT, so
   `instance.id` was `None` for exactly the window in which a graph gets assembled.

   The visible symptom was four integration tests failing on `NotNullViolationError` for
   `scans.repository_id`, because their setup reads `repository.id` before a flush. That
   is a test bug, and it was **masking a product one**: `pipeline._persist_history` builds
   `FileChange(commit_id=commit.id)` for every file a commit touched, with no flush in
   between. Every one of those rows carried `commit_id=None`, `file_changes.commit_id` is
   NOT NULL, and `_persist_history` catches broadly and returns the reason as a PARTIAL
   status — so a real scan would have completed, reported PARTIAL, and **silently lost
   its entire commit history and every per-file churn record**. That is the data this
   phase added the table for and the data phase 4's ranking is built on.

   Nothing local could have found it: the four tests failed in setup before reaching the
   pipeline, so even in CI the pipeline path went unexercised until they were fixed, and
   the whole `file_changes` feature was designed, migrated and shipped in a phase whose
   integration tests could not run on the development machine. The mixin now assigns the
   key in `__init__`, keeps the column default for paths that bypass it, and four
   database-free unit tests pin the behaviour so the trap cannot return quietly.

7. **A cleanup assertion that was checking the wrong directory.**
   `test_the_clone_is_removed_whatever_happens` asserted `clone_root` was empty, but the
   settings fixture pointed `clone_root` at `tmp_path` while the `git_repo` fixture built
   its source repository in that same `tmp_path`. The leftover it tripped on was the
   fixture, not a clone — the pipeline had removed its own tree correctly. Left alone it
   would have failed in the other direction too: a future change that genuinely leaked a
   clone would have been indistinguishable from the fixture being present, and the failure
   message would have sent the next person after the wrong bug.

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
