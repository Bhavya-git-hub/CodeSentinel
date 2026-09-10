# Phase 2 — Sandbox

## Scope delivered

- `sandbox/Dockerfile.analysis` — Python 3.11 slim, exactly pinned analysis tools,
  non-root user, and a build-time version manifest at `/opt/codesentinel/tool-versions.json`.
- `sandbox/write_tool_versions.py` — generates that manifest from the *installed*
  distributions, and fails the build if a tool is missing.
- `app/services/sandbox/` — the `Sandbox` service: one throwaway container per command,
  full isolation set, timeout-kill, capped output capture, orphan reaping.
- Unit tests over the requested container configuration (no daemon needed) and
  integration tests against a real daemon.
- `CODESENTINEL_REQUIRE_INTEGRATION`, which turns an unavailable dependency into a
  failure rather than a skip.
- ADRs 0009 and 0010.

## Acceptance

All three criteria met, in CI run **34525145554**: 93 tests passed, **0 skipped**.

| Criterion | Evidence |
|---|---|
| A container attempting a network call fails | Interface list inside the container is exactly `["lo"]`; outbound connect and DNS resolution both fail |
| An infinite-loop command is killed at the timeout | `while True: pass` returns `TIMED_OUT` within its 5s bound, `exit_code is None`, and no container is left running |
| No containers remain after a failed run | Asserted after a non-zero exit, after a timeout, and after an exception raised mid-run |

The timeout test asserts on **wall-clock duration**, which is what separates killing the
container from abandoning the wait — both return promptly, only one leaves the host clean.

Network isolation is asserted on the container's own interface list rather than by
reaching for an external host, so the test proves isolation rather than proving the CI
runner's connectivity.

## Correction to ADR 0005

Phase 1 recorded that Phase 2 was "hard-blocked" until Docker was installed locally. That
was wrong in one respect: GitHub Actions runners provide a real Docker daemon, so the
acceptance criteria are fully demonstrable in CI. Local Docker remains absent, so
`docker compose up` is still unverified — that part of ADR 0005 stands.

## Defects CI caught

1. **Dockerfile heredoc** — needs a BuildKit syntax directive to parse. Replaced with a
   script file, which is also lintable.
2. **Source tree unreadable by the sandbox uid** — the significant one. The container runs
   as uid 10001, which never matches the host user that made the clone, so a clone that is
   not world-readable is invisible inside the container. Every analyser would see an empty
   workspace, find nothing, and the scan would look healthy: **a clean report for a
   repository nobody analysed**. The sandbox now refuses such a tree with a message naming
   the mode and the fix.
3. **Over-specific assertion** — the read-only-mount test named one kernel refusal message;
   a read-only mount and a uid mismatch produce different, equally correct refusals.

## Obligations this places on later phases

- **Phase 3 ingestion must produce world-readable clones** (`chmod o+rX`). The sandbox
  refuses anything else rather than analysing an empty directory.
- **Phase 5 cannot open the network** to make dependency installation work. It must
  pre-populate a read-only wheel cache or mark coverage `skipped` with the reason
  (ADR 0009).
- **`reap_orphans()` is unsafe with more than one worker per host** — it removes every
  labelled container, including another worker's live ones. Scoping it to the worker's own
  identity belongs with the phase 3 pipeline that introduces concurrent scans (ADR 0010).
- **ADR 0006 is still open**: how the worker reaches the Docker daemon. Nothing in phase 2
  needed it, because the tests drive the sandbox directly rather than through a worker
  container. Phase 3 has to decide it.

## Still not met from phase 1

`docker compose up` remains unverified; Docker is not installed on the development
machine. `docker compose build` passes in CI.
