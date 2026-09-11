# 0006. Worker access to the Docker daemon is deferred to phase 2

**Status:** superseded by [0013](0013-worker-docker-access.md) — 2026-09-11

## Context

From phase 2 the Celery worker must launch analysis containers. In a containerised
deployment that means the worker container needs to reach a Docker daemon, and the usual
shortcut is to bind-mount `/var/run/docker.sock` into it.

That shortcut is a privilege escalation path: a process that can talk to the Docker socket
can start a privileged container mounting the host filesystem, which is root on the host.
Since the worker is the component that handles untrusted repository content, it is
precisely the component where that capability is most dangerous. Adding it casually would
undermine the isolation C1 exists to provide.

## Decision

Do not mount the Docker socket now. `docker-compose.yml` carries a comment marking the
gap. The options -- direct socket mount, a filtering socket proxy, a rootless daemon, or
running the worker outside the container -- are evaluated in phase 2 when the sandbox is
actually built, with the threat model in front of us.

## Consequences

- Phase 1's compose stack cannot run analyses. It is not supposed to.
- Phase 2 must open with this decision rather than inheriting it by default.
- Phase 2 did not in fact answer this: its tests drive the `Sandbox` service directly,
  so no worker needed a daemon. The question reached phase 3 still open and is settled
  there — see [ADR 0013](0013-worker-docker-access.md).
