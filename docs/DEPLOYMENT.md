# Deploying CodeSentinel

This service clones repositories chosen by its callers and executes their tooling. That
single fact drives every instruction below; where a step looks paranoid, it is answering
that.

## Before you start: what this system is

A caller sends a URL. The worker clones it onto the host and runs analysers against it in
containers. So an instance of CodeSentinel is, from the network's point of view, a machine
that will fetch and analyse whatever a reachable party names — which makes three things
non-optional rather than best practice:

1. **The API must be authenticated.** It refuses to start in production without keys.
2. **The worker must not be reachable from the internet.** Only the API and the frontend
   are public surfaces.
3. **The Docker socket belongs to the proxy, never the worker.** See
   [ADR 0015](adr/0015-socket-proxy-filters-endpoints-not-bodies.md) for exactly how far
   that protection goes — it is narrower than it first appears.

## Requirements

- Docker Engine 24+ and Compose **v2.24.4 or newer** (the production overlay uses the
  `!override` tag; older Compose silently appends instead of replacing, which would leave
  the database port published).
- A host with a Docker daemon the worker can reach through the proxy.
- Disk for clones: at least `max_repo_size_mb` × (worker replicas) × 2, plus headroom.

## 1. Configure

```bash
cp .env.production.example .env
```

Fill in the three required values. There are no working defaults, and compose refuses to
start without them — a default credential that works is a credential nobody changes.

```bash
# Database password
openssl rand -base64 32

# One API key per consumer, so they can be revoked individually
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set `CODESENTINEL_CORS_ORIGINS` to the exact origin serving the frontend. Not a wildcard:
the API is authenticated, and a wildcard origin plus a browser-held key is a credential any
site can borrow.

## 2. Start

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

What the overlay changes from the development stack: production environment, real
credentials, published database and Redis ports removed, restart policies, memory limits,
and two replicas each of the API and worker.

## 3. Migrate

Migrations are **not** run automatically at start-up. Two API replicas racing to migrate
the same database is a corruption risk, and an automatic migration makes a rollback into
a data-loss event. Run it once, deliberately:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api \
  alembic upgrade head
```

## 4. Verify

```bash
# Readiness: reports unhealthy while any dependency is down, by design.
curl -fsS http://localhost:8000/health/ready

# Authentication is live — this must return 401.
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/api/v1/scans \
  -H 'Content-Type: application/json' -d '{"url":"https://github.com/psf/requests"}'

# With a key, a hostile URL must still be refused with 422.
curl -s -X POST http://localhost:8000/api/v1/scans \
  -H "X-API-Key: $YOUR_KEY" -H 'Content-Type: application/json' \
  -d '{"url":"ext::sh -c whoami"}'
```

If the second command returns anything but `401`, stop and check that
`CODESENTINEL_ENVIRONMENT=production` and `CODESENTINEL_API_KEYS` reached the container.

## Operating notes

**Scaling.** Raise `deploy.replicas` on `worker`. Keep Celery concurrency at 1 per worker:
a scan holds a clone and several containers, so parallelism belongs at the replica level
where the memory limit applies per scan.

**Worker identity.** Each worker reaps only its own orphaned containers, keyed on
`worker_id`, which defaults to the hostname. Compose gives each replica a distinct
hostname. If you deploy workers some other way, ensure each has a **stable, distinct**
`CODESENTINEL_WORKER_ID` — stable because a restarted worker must recognise what its
previous incarnation left behind, distinct because reaping another worker's live
containers kills a scan in progress (ADR 0010).

**Disk.** Clones live on the `clones` volume and are deleted when a scan ends, including
on failure. If that volume grows, something is leaving trees behind — check the logs for
`clone.cleanup_failed`.

**Rate limiting** is a fixed window in Redis, per API key. It fails closed: if Redis is
unreachable, submissions return 503 rather than becoming unmetered. Existing scans are
unaffected.

## What is NOT production-hardened

Stated plainly, because a deployment guide that lists only what works is the same failure
this project spends its whole design avoiding.

- **The worker's integrity is a security boundary.** The socket proxy filters endpoints,
  not request bodies, so a compromised worker can still create a privileged container and
  reach host root (ADR 0015). This is tolerable only because the worker never executes
  target code — everything that runs goes in the sandbox. **Do not add anything to the
  worker that executes target-controlled input.**
- **No TLS.** Terminate it at a reverse proxy in front of the API and frontend. Nothing
  here does.
- **`docker compose up` has never been executed by this project.** CI validates and builds
  the compose files on every push, which proves they are well-formed and the images build;
  it does not prove the stack runs. Your first deploy is the first real run.
- **No backup or retention policy.** Scan rows and their findings accumulate without
  bound. There is no pruning job.
- **API keys are compared as plain secrets from the environment.** There is no rotation
  mechanism, no per-key scoping and no audit trail beyond the request log.
- **No metrics endpoint.** Logs are structured JSON via structlog; there is no Prometheus
  surface.
