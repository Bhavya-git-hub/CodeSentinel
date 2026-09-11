# 0019. Retention is opt-in, prunes only terminal scans, and deletes emptied repositories

**Status:** accepted — 2026-09-11

## Context

`docs/DEPLOYMENT.md` recorded that "scan rows and their findings accumulate without bound.
There is no pruning job." Writing one raised three questions whose obvious answers are all
wrong.

**What does deleting a scan actually free?** `file_metrics`, `findings`, `dependencies`
and `predictions` all carry `scan_id` with `ON DELETE CASCADE`, so they go with the scan.
But `files`, `commits` and `file_changes` cascade from `repositories`, not from scans —
and those are the bulk. A single scan of psf/requests writes 4,881 commit rows plus a
file-change row for every path each of them touched. A pruner that deleted only scans
would report thousands of rows removed and leave the database growing at exactly the same
rate, which is the most demoralising possible outcome: a job that appears to work.

**What does a retention of zero mean?** `retention_days=0` is the natural way to spell
"disabled" in a setting, and it is also the value for which the cutoff arithmetic yields
`now` — selecting every scan ever recorded. The two readings are one typo apart and one of
them is unrecoverable.

**What about a scan that never finished?** A PENDING or RUNNING scan older than any
sensible cutoff exists. It is not expired.

## Decision

**Opt-in, default 0 = keep forever.** An upgrade must not begin deleting an operator's
scan history because they installed a new version. The safe direction for a new default
is to keep.

**Zero is refused, not interpreted.** `prune_scans` raises `RetentionDisabledError` rather
than computing a cutoff from `retention_days <= 0`. The caller checks first. This is a
guard against a misread setting, not against a bug in the caller — the call that would
wipe the history looks completely ordinary at the call site.

**Emptied repositories are deleted too.** After the scan delete, any repository with no
remaining scans goes, taking its files, commits and file changes with it. This is the step
that reclaims the space. It is safe because `submit_scan` writes the repository and its
first scan in one transaction, so a *committed* repository with no scans is a leftover
rather than an in-flight submission.

**Only terminal scans are pruned** — SUCCEEDED, PARTIAL, FAILED. An old RUNNING scan is
stuck, and deleting it pulls the row out from under a worker still writing to it, turning
a stuck scan into a foreign-key error in the middle of a pipeline. It would also hide the
fact that scans get stuck at all, which is the thing somebody needs to see. Stuck scans
need their own answer; this is deliberately not it.

**The schedule is absent when retention is off.** `beat_schedule()` returns `{}` rather
than scheduling a job that no-ops. An operator checking `celery inspect scheduled` to find
out whether this deployment prunes would otherwise read the entry and conclude it does.

**The cutoff is computed from the clock, not from the last run.** So a missed run costs
nothing: the next pass deletes everything the missed one would have. That is why `beat`
can carry an `expires` option and why a restart cannot stampede.

`retention_days` is **not** in `reproducibility_snapshot()`. C5 records the configuration
that produced a result; how long that result is then kept is not part of producing it, and
including it would imply two scans run under different retention settings are not
comparable.

## Consequences

- Deleting a repository deletes its defect-prediction history. The next scan of that URL
  starts from an empty commit table and re-mines it from the clone, so nothing is
  unrecoverable, but SZZ labels are recomputed rather than carried forward.
- There is exactly one `beat` service and the production overlay pins it to one replica.
  Two schedulers sharing a schedule dispatch every entry twice, and this entry deletes
  rows.
- `beat` and `worker` must agree on `CODESENTINEL_RETENTION_DAYS`: beat decides whether
  the entry exists, the worker decides the cutoff it applies. A mismatch produces a job
  that fires and then declines to act, which reads as a broken schedule.
- This is a retention policy, not a backup policy. There is still no backup, and pruning
  makes that more consequential rather than less.
- Pruning is a single unbounded `DELETE`. On a database with years of history the first
  run after enabling retention will be long and will hold locks. Nothing here batches it.
