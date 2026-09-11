# 0015. The socket proxy filters endpoints, not request bodies

**Status:** accepted — 2026-09-11 (obligation closed by [0017](0017-socket-proxy-validates-request-bodies.md))

Corrects a claim in [ADR 0013](0013-worker-docker-access.md).

## Context

ADR 0013 chose a filtering socket proxy over a raw `/var/run/docker.sock` mount, and
described it as one that "exposes only the container create/start/wait/logs/remove calls
the `Sandbox` service uses, and refuses everything else — privileged flags, host bind
mounts, image builds."

Implementing it showed that the middle item is not true of any off-the-shelf proxy.

A Docker socket proxy of the usual kind (`tecnativa/docker-socket-proxy` and its
relatives) is an HTTP reverse proxy that allows or denies by **endpoint and method**. It
can refuse `/build`, `/networks`, `/volumes`, `/exec` and every `GET`-only path. It cannot
refuse *a field inside the JSON body of a permitted request*, because it does not parse
the body at all.

`POST /containers/create` is a permitted request — the sandbox cannot work without it —
and `Privileged: true`, `Binds: ["/:/host"]` and `CapAdd: ["SYS_ADMIN"]` all live in that
body. So a proxy configured to let the sandbox work also lets a compromised worker create
a privileged container that mounts the host root. The escalation path ADR 0013 set out to
close is narrowed, not closed.

Shipping the proxy while leaving 0013's description standing would be worse than shipping
nothing: the next person reads the ADR, believes host root is unreachable from the worker,
and builds on a guarantee that does not exist.

## Decision

Ship the endpoint proxy, and state exactly what it does and does not do.

**What it stops.** The worker cannot build images, create networks or volumes, exec into
running containers, read other containers' state, or reach any Docker API outside the
container endpoints. The host socket is mounted into the proxy alone; the worker holds no
socket and has no path to one if the proxy is unreachable.

**What it does not stop.** A worker that executes attacker-controlled code can still issue
`POST /containers/create` with `Privileged: true` or a host bind mount, and thereby reach
host root.

**Therefore the worker's own integrity remains a security boundary**, and the properties
that keep it intact are the ones already established: the worker never executes target
code (ADR 0011 — it clones and reads bytes; everything that *runs* goes in the sandbox),
and the sandbox itself has no network and no writable mount.

Body-level filtering — a small proxy that parses `/containers/create` and rejects any
`HostConfig` the `Sandbox` service does not itself set — is the remaining work. It is
recorded here as an obligation rather than implemented now, because it is a component to
write and test rather than a compose file to configure, and pretending otherwise is how
the gap gets forgotten.

## Consequences

- `docker-compose.yml` gains a `docker-proxy` service holding the socket, and the worker
  reaches it over `DOCKER_HOST=tcp://docker-proxy:2375`. No service but the proxy mounts
  the socket.
- The proxy's configuration is deny-by-default: every capability group is `0` except
  `CONTAINERS`, and `POST` is enabled because container creation requires it.
- **A later phase must add body-level filtering** of `/containers/create`. Until it does,
  the worker is trusted not to be compromised, and that trust is written down here rather
  than assumed.
- This does not weaken C1. The sandbox's isolation is unchanged; what is bounded here is
  the blast radius of a worker that has already been taken over, which was never a
  guarantee the container isolation made.
