# 0010. Containers are removed in a `finally`, and timeouts kill rather than abandon

**Status:** accepted — 2026-09-11

## Context

Two failure modes were called out as pitfalls for this phase: containers leaking on
exception, and timeouts that abandon the exec rather than killing the container. Both
have tempting shortcuts.

**`auto_remove=True`** looks like the obvious answer to leaks. It races with reading the
container's logs and exit state: the container can vanish before the output is drained,
producing a silently empty result that looks like a tool that printed nothing.

**`container.wait(timeout=N)`** looks like the obvious answer to timeouts. It only times
out the *HTTP request*. The container keeps running, holding its memory and pegging its
CPU quota, indefinitely. An infinite loop in a target's test suite becomes a permanently
consumed host core, and the scan reports a timeout as though it had been contained.

## Decision

- Container creation and removal are wrapped in a context manager whose `finally` calls
  `remove(force=True)`. `auto_remove` is not used.
- On `ReadTimeout`, the container is explicitly `kill()`ed before the result is built.
- A removal that fails is logged at error level with the container id, never swallowed.
  A container that could not be removed is a host resource leak, and the operator needs
  to know it exists.
- Every container carries a `codesentinel.owner` label, and `Sandbox.reap_orphans()`
  removes any that are found. This covers the case no `finally` can: a worker killed by
  SIGKILL, or a host reboot mid-run. It returns a count rather than cleaning silently, so
  an accumulating leak stays visible.

## Consequences

- The integration tests assert on wall-clock duration for the timeout case. That is the
  assertion that distinguishes killing from abandoning -- both return promptly, only one
  leaves the host clean.
- One test deliberately raises from inside `run()` to prove the `finally` covers an
  exception path, which is exactly the case `auto_remove` would not have covered.

## A related exposure, still open

`reap_orphans()` removes every container carrying the owner label, so a worker starting
up will remove containers belonging to *another* worker still running on the same host.
That is safe for the current single-worker deployment and is not safe for a scaled one.
Recorded here rather than fixed now; the fix is to scope reaping to the worker's own
identity, and it belongs with the phase 3 pipeline that introduces concurrent scans.
