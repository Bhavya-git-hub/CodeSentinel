# 0004. Every metric column is nullable

**Status:** accepted — 2026-09-11

## Context

`file_metrics` holds complexity, maintainability, churn, risk and coverage. Target
repositories routinely produce partial data: an unparseable file has no complexity, a
repository whose tests will not install offline has no coverage at all, and a file added
in the scanned commit has no churn history.

Constraint C3 and anti-pattern #2 forbid substituting `0` for missing data. A file with
no coverage data is not a file with 0% coverage: the first should be surfaced as a gap,
the second should be at the top of the untested-risk backlog.

The same argument applies to `commits.is_bugfix` and `commits.is_defect_inducing`. A
commit that has not been labelled is not a commit labelled "not a defect" -- defaulting
those to `False` would inject unverified negative examples straight into the phase 8
training set.

## Decision

Every metric column is nullable with no default. Both defect-label columns are tri-state
`Boolean` (`True` / `False` / `NULL`), where `NULL` means "not yet labelled".

## Consequences

- Missing data is representable and is preserved end to end.
- Every consumer must handle `None`. This is the point: it forces the question "what does
  absent mean here?" at each use site instead of silently answering it with zero.
- Aggregations must exclude NULLs explicitly rather than averaging them in as zeros.
- Enforced by unit tests over the model metadata, so a later `NOT NULL DEFAULT 0` fails
  the build rather than quietly changing what a report means.
