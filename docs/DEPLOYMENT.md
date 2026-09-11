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

## 2. Prepare the host

Two things must exist on the host before the stack starts. Both were found by the first
real `docker compose up` rather than reasoned out in advance, and both fail in ways that
look like something else.

```bash
# The clone directory. A bind mount, not a named volume -- the worker asks the daemon to
# bind-mount each clone into an analysis container, and the daemon resolves that path on
# the HOST, so it has to mean the same thing on both sides. A bind mount does not inherit
# ownership from the image, so it must be chowned to the image's uid.
sudo mkdir -p /var/lib/codesentinel/clones
sudo chown -R 10001:10001 /var/lib/codesentinel

# The Docker socket's group. The proxy runs unprivileged and the socket is root:docker
# mode 660, so without this it cannot read the socket at all.
echo "CODESENTINEL_DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)" >> .env
```

**Both of these are now checked at start-up rather than trusted.** If the gid is wrong the
proxy refuses to start; if the clone directory is not writable the worker refuses to start,
naming the path and saying to chown it. Both used to fail much later and as something else:
the proxy returned 500 to every request while every layer above it degraded politely into
"the sandbox was unavailable", and the worker failed one scan at a time on `mkdtemp`. A
deployment that does not start gets investigated; one that comes up green does not.

Set `CODESENTINEL_CLONE_ROOT` if you want the clones somewhere else; it is used as both
sides of the bind mount, so the two cannot drift apart.

## 3. Start

```bash
# Terminating TLS somewhere else (an existing ingress, a cloud load balancer):
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Terminating TLS here, with a certificate obtained automatically over ACME:
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.tls.yml up -d
```

What the production overlay changes from the development stack: production environment,
real credentials, published database and Redis ports removed, restart policies, memory
limits, two replicas each of the API and worker, and a single `beat` scheduler.

What the TLS overlay adds on top: Caddy on 443, and — the part that matters —
`ports: !override []` on the API and the frontend, so neither is reachable except through
the proxy. Without that, a firewall gap leaves the plaintext API listening beside the
encrypted one and nothing in the application can tell which route a caller took. It needs
`CODESENTINEL_DOMAIN` to be a hostname that already resolves to this machine; a
certificate is proof of control over a name, and there is no way to prove control of one
that does not point here. See [ADR 0021](adr/0021-tls-is-a-separate-overlay.md).

## 4. Migrate

Migrations are **not** run automatically at start-up. Two API replicas racing to migrate
the same database is a corruption risk, and an automatic migration makes a rollback into
a data-loss event. Run it once, deliberately:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api \
  alembic upgrade head
```

## 5. Verify

In production the API publishes no port of its own — two replicas cannot share one — so
these go through the frontend, which proxies `/api/` and `/health` on the compose network.
With the TLS overlay, use `https://$CODESENTINEL_DOMAIN` instead of `http://localhost:5173`.

```bash
BASE=http://localhost:5173   # or https://$CODESENTINEL_DOMAIN with the TLS overlay

# Readiness: reports unhealthy while any dependency is down, by design.
curl -fsS "$BASE/health/ready"

# Authentication is live — this must return 401.
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$BASE/api/v1/scans" \
  -H 'Content-Type: application/json' -d '{"url":"https://github.com/psf/requests"}'

# With a key, a hostile URL must still be refused with 422.
curl -s -X POST "$BASE/api/v1/scans" \
  -H "X-API-Key: $YOUR_KEY" -H 'Content-Type: application/json' \
  -d '{"url":"ext::sh -c whoami"}'

# The database and Redis must not be reachable from the host at all.
! timeout 2 bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/5432' && echo "postgres closed"
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

**Retention** is off by default, and off means scans accumulate forever. Set
`CODESENTINEL_RETENTION_DAYS` on both `worker` and `beat` — beat decides whether the
pruning job exists, the worker decides the cutoff it applies, and a mismatch is a job that
fires and declines to act. Pruning also deletes repositories left with no scans, which is
the step that actually frees the disk: commits, files and file changes cascade from the
repository row rather than from the scan, and one scan of a large repository writes several
thousand commit rows. A scan still PENDING or RUNNING is never pruned however old — that is
a stuck scan, not an expired one. The first run after enabling retention on an old database
will be a long unbatched `DELETE`. See
[ADR 0019](adr/0019-retention-is-opt-in-and-deletes-repositories.md).

**Metrics** are off by default. `CODESENTINEL_METRICS_ENABLED=true` serves Prometheus text
at `/metrics`, **unauthenticated** — a scraper has no key to present — so scrape it from
inside the compose network. The TLS overlay deliberately does not proxy it. A gauge it
cannot compute is omitted rather than reported as zero, so alert on
`absent(codesentinel_scans)` and on `codesentinel_database_reachable == 0` rather than
expecting a zero. See [ADR 0018](adr/0018-metrics-are-opt-in-and-unauthenticated.md).

## The frontend and the API key

The browser has to authenticate too, and a key in a browser bundle is not a secret —
anyone who can load the page can read it. The client therefore looks for a key in this
order:

1. `localStorage.getItem("codesentinel.apiKey")` — per viewer, not shipped in the bundle.
2. `VITE_CODESENTINEL_API_KEY` — baked in at build time, visible to every viewer.

**For anything but a single-tenant internal deployment, use neither.** Put a gateway in
front of the API that adds `X-API-Key` server-side, leave both unset, and the browser
never holds a credential at all. That is the only topology where the key stays a secret.

If you do use option 1, a viewer sets it under **Settings** in the interface. A 401 from
the API points there rather than reporting a generic failure, because the fix is a
credential, not a retry.

The panel shows a configured key as `name:…` and never renders the secret half at any
length — a prefix on screen is a prefix in a screenshot. It also says when the key came
from the bundle rather than from the viewer, because presenting a published credential
identically to a private one describes it wrongly. And a save that `localStorage` refused
— a private window, blocked site data — is reported as refused, rather than saying "saved"
and 401ing on the next request.

**Name your keys.** `CODESENTINEL_API_KEYS` accepts `name:secret`, and the name is what
every log line for that request carries. Without it the most the logs can tell you is that
*a* valid key submitted four hundred scans, which does not say whether that was the CI
integration after a merge queue backed up or a leaked credential, and leaves rotating
everything as the only safe response. See
[ADR 0020](adr/0020-api-keys-carry-a-name.md).

## What is NOT production-hardened

Stated plainly, because a deployment guide that lists only what works is the same failure
this project spends its whole design avoiding.

- **Public ACME issuance has never been exercised, and it is now the only part that has
  not been.** CI runs all three compose files on every push — the base stack end to end,
  and the production and TLS overlays together with two API replicas, two workers, the
  port removals checked by connecting rather than by reading config, TLS terminated, and
  authentication live through the proxy. What it cannot do is obtain a real certificate:
  an ACME server has to reach the host by a name that resolves to it, and no runner has
  one. CI uses `localhost`, for which Caddy issues from its own internal CA and never
  contacts an ACME server at all, so the issuance path itself runs for the first time on
  your deployment.

  **Use staging for the first deploy.** Set
  `CODESENTINEL_ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory`, confirm
  a certificate is issued, then remove it. Production allows five failed authorisations
  per hostname per hour; a DNS record that is not quite right burns all five in a couple
  of restarts, and the lockout arrives exactly when someone is trying to fix it. If Caddy
  cannot get a certificate, everything behind it is unreachable rather than degraded, so
  check its logs first.
- **No backup policy.** Retention now exists and bounds growth, but nothing here backs
  anything up, and pruning makes that more consequential rather than less. The database is
  a plain PostgreSQL volume; back it up the way you back up any other.
- **API keys are live secrets in the environment.** They now carry a name, so the logs say
  which key did what and which one to revoke (ADR 0020). What is still absent: hashing at
  rest, so an environment leak is a credential leak; any rotation mechanism beyond editing
  the environment and restarting; expiry; and per-key scoping — every key can do
  everything. A hashed keys table is the answer when any of those matters.
- **Metrics are thin.** Scan counts by status, repository count, and per-route request
  counters. There is no scan-duration histogram and no queue-depth gauge; both are worth
  having and neither is here.
- **Defect prediction ranks coarsely.** The model buckets commits by size, so every commit
  in a bucket gets an identical probability and the report's "most likely to have
  introduced a defect" list is arbitrary *within* its top bucket rather than a true
  ranking. `sample_size` and `model_version` travel with each row so the shape is visible.
  Read that list as a set, not as an order.
- **Stuck scans have no answer.** A scan that dies mid-pipeline stays RUNNING forever. The
  pruner deliberately will not collect it — deleting a row a worker may still be writing to
  turns a stuck scan into a foreign-key error, and silently eating them would hide that
  they happen at all. Nothing else collects it either, so watch
  `codesentinel_scans{status="running"}` for a number that only grows.
