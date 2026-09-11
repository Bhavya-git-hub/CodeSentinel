# 0017. The socket proxy validates request bodies, by allowlist

**Status:** accepted — 2026-09-11

Closes the obligation recorded in [ADR 0015](0015-socket-proxy-filters-endpoints-not-bodies.md).

## Context

ADR 0015 shipped an off-the-shelf endpoint proxy and stated plainly what it could not do:
it allows or denies by path and method, and `Privileged`, `Binds`, `CapAdd` and `Devices`
all live inside the body of `POST /containers/create` — a request the sandbox cannot work
without. A worker that had been taken over could still ask for a privileged container
mounting the host root, and the proxy would forward it.

That left the worker's own integrity as a security boundary, tolerable only because the
worker never executes target code (ADR 0011). "Tolerable because of a property we are
maintaining by discipline" is a weaker position than the rest of this system holds, and it
was written down as owed rather than solved.

## Decision

Replace the endpoint proxy with one that parses the body.

**The validator is a pure function** — `socket_filter.validate(method, path, body)` — with
no sockets, no I/O and no daemon. ADR 0013 justified a proxy on the grounds that it is
"small enough to audit", and a validator entangled with transport is not auditable, only
reviewed. The transport lives separately in `app/proxy.py` and makes no decisions.

**The rule is an allowlist of `HostConfig` keys with constrained values, never a denylist
of dangerous ones.** This is the load-bearing choice. A denylist is wrong the day Docker
adds a field: the new key passes unexamined and nobody notices until it is used. An
allowlist fails closed on exactly that case, and the refusal names the key, so admitting a
legitimate one is a deliberate edit to this file rather than an accident.

Permitted `HostConfig` keys are the ones the `Sandbox` service actually sets, and several
carry value constraints rather than merely being present: `NetworkMode` must be `none`,
`ReadonlyRootfs` must be true, `CapDrop` must include `ALL`, `SecurityOpt` may only be
`no-new-privileges`, and every mount must be a read-only bind. A create request with no
`HostConfig` at all is refused, because the daemon would then apply its own defaults — a
writable root filesystem and a bridged network.

The proxy runs from the backend image with a different command, so it adds no second
dependency tree and its validator is covered by the existing test suite.

## Consequences

- **A compromised worker can no longer reach host root through the daemon.** The
  escalations ADR 0015 named are each refused, with a test per escalation.
- The worker still holds no socket. The proxy remains the only component that does.
- **Adding a sandbox option now requires editing the allowlist.** That is friction by
  design: the failure this prevents is a new option passing unexamined, and the same edit
  that adds a capability is the edit that authorises it.
- The filter's fixture is the `Sandbox` service's real create body, so a change to the
  sandbox that this filter would reject surfaces as a failing test rather than as a
  container that will not start.
- **The forwarding layer is untested.** The validator has 34 tests; that the proxy
  correctly relays bytes to a real daemon has not been demonstrated, because neither this
  machine nor CI runs the compose stack. First deploy is the first exercise of it.
