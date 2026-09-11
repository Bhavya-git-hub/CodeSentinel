# 0013. The phase 3 worker gets no Docker access; the mechanism is chosen for phase 5

**Status:** accepted — 2026-09-11

Supersedes [ADR 0006](0006-worker-docker-access.md).

## Context

ADR 0006 deferred the question of how the Celery worker reaches a Docker daemon, and said
phase 2 would answer it. Phase 2 did not: its tests drive the `Sandbox` service directly
rather than through a worker container, so nothing in that phase needed the answer. The
question arrived at phase 3 still open, and phase 3 is the first phase that actually ships
a worker.

The shortcut remains what it was -- bind-mount `/var/run/docker.sock` into the worker --
and so does the objection. A process that can talk to the Docker socket can start a
privileged container that mounts the host filesystem, which is root on the host. The
worker is the component that handles untrusted repository content, so it is the single
worst place in this system to put that capability.

The relevant new fact is that **phase 3 runs no containers at all**. Cloning, inventory
and history mining are host-side operations under ADR 0011. The worker needs a database
and a broker; it does not need a daemon.

## Decision

The phase 3 worker is granted **no Docker access**. `docker-compose.yml` keeps its comment
marking the gap, and no socket is mounted.

The mechanism for phase 5, when analysers land and containers actually have to start, is
decided now so that phase does not open with the same unanswered question a third time:

**A filtering socket proxy**, not a direct socket mount. The worker talks to a proxy that
exposes only the container create/start/wait/logs/remove calls the `Sandbox` service uses,
and refuses everything else -- privileged flags, host bind mounts, image builds. The
proxy, not the worker, is the component that holds the dangerous capability, and it is
small enough to audit.

Rejected alternatives:

- **Direct socket mount.** Simplest, and hands host root to the component that processes
  untrusted input. No.
- **Rootless daemon.** Genuinely better isolation, but it constrains the deployment host
  in ways we cannot assume, and it does not remove the need to restrict *which* API calls
  the worker may make.
- **Worker outside the container.** Sidesteps the problem by abandoning containerised
  deployment, which is not a trade we want to make for this.

## Consequences

- Phase 3's compose stack can ingest repositories but cannot analyse them. That is the
  correct behaviour for the phase, not a limitation to work around.
- Phase 5 opens with an implementation task, not a decision. If the proxy turns out to be
  wrong once the threat model is in front of us, that is a new ADR superseding this one --
  which is the mechanism working, not a failure of it.
- `Sandbox.run()` must keep to the narrow set of daemon calls named above, or the proxy
  becomes a thing people widen rather than a thing that constrains.
- **`reap_orphans()` still needs scoping to the worker's own identity before concurrent
  scans exist** (ADR 0010). It removes every labelled container, including another
  worker's live ones. Phase 3 introduces the worker but no concurrent sandboxes, so the
  bug is not reachable yet; phase 5 cannot ship without fixing it.
