# 0009. Sandbox isolation is applied as a set, with no opt-out

**Status:** accepted — 2026-09-11

## Context

Constraint C1 requires all analysis of target repositories to run inside a sandbox. The
natural API is a `Sandbox.run()` that takes keyword arguments for the restrictions, so a
caller can relax one when a tool needs it. Phase 5 will make that temptation concrete:
most target repositories cannot install their dependencies without network access, and
`allow_network=True` would make coverage work for far more of them.

## Decision

There is no argument that weakens isolation. Every container gets, unconditionally:

| Restriction | What it stops |
|---|---|
| `network_mode="none"` + `network_disabled` | Exfiltration of anything the container reads; pulling a second stage |
| Read-only bind mount at `/workspace` | Analysis modifying the clone that phases 4 and 8 mine |
| `read_only=True` root filesystem | Persisting anything outside the discarded tmpfs |
| `tmpfs` at `/tmp`, `noexec,nosuid` | Writing then executing a dropped binary |
| `user="10001:10001"` | Running as root even if the image is rebuilt or substituted |
| `cap_drop=["ALL"]` | Every Linux capability |
| `no-new-privileges` | A setuid binary regaining what `cap_drop` removed |
| `mem_limit` **and** `memswap_limit` | Memory exhaustion; without the second, the limit is soft |
| `cpu_quota` / `cpu_period` | Starving the host of CPU |
| `pids_limit` | A fork bomb in a target's test suite |
| `init=True` | Zombie children accumulating against the PID limit |
| `log_config` max-size | Unbounded daemon-side logs filling host disk |

The user id is set explicitly even though the image already declares `USER analyst`,
because relying on the image alone means a rebuilt or substituted image could silently
run as root.

## Consequences

- Phase 5 cannot solve the offline-dependency problem by opening the network. It must
  either pre-populate a read-only wheel cache or mark coverage `skipped` with the reason,
  which is what the brief already requires.
- Some analysis tools may need paths made writable. The answer is another tmpfs mount or
  an environment variable pointing at `/tmp` (the image already does this for `HOME`,
  `PYLINTHOME` and the semgrep settings file), never a relaxation of the root filesystem.
- The restrictions are asserted at two levels: unit tests over the requested
  configuration, which run everywhere, and integration tests that ask a real daemon to
  actually stop something. Neither is sufficient alone -- a unit test can pass against a
  flag Docker ignores, and integration tests cannot run where there is no daemon.
