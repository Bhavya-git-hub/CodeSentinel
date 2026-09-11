# 0016. The API authenticates, and refuses to start in production without keys

**Status:** accepted — 2026-09-11

## Context

Until now the API was unauthenticated. That was correct for phases 1-8, which were never
exposed to a network, and it stops being correct the moment anyone deploys it.

The exposure is not the usual one. A typical unauthenticated API leaks or mutates its own
data. This one takes a URL from a caller and, on the strength of that URL alone, clones a
repository onto the host and starts containers. An open instance is therefore a machine
that will fetch and analyse whatever any reachable party names, for as long as they keep
asking: the clone target is attacker-chosen, the work is expensive, and both properties
are available to anyone who can reach the port.

The question was not whether to authenticate but what happens when someone deploys
without configuring it.

## Decision

API key authentication on every `/api/v1` route, supplied in `X-API-Key`. Health probes
stay unauthenticated — an orchestrator cannot present a key, and readiness reveals only
whether dependencies are reachable.

**The load-bearing decision is that it fails closed.** `assert_auth_configured` runs in the
application factory, and an instance with `CODESENTINEL_ENVIRONMENT=production` and no
keys **raises at boot**. It does not log a warning and serve.

The softer option was considered and rejected. A warning produces an instance that came up
successfully, passes its health check, and serves traffic — and nobody reads the start-up
logs of a service that is working. The failure mode of failing closed is a deployment that
does not start, which a deploy pipeline surfaces immediately. The failure mode of warning
is an open instance nobody notices until it is found.

Keys are compared with `secrets.compare_digest`, and every configured key is compared even
after a match, so neither the value nor the position of the matching key leaks through
timing. Rejections do not distinguish "no key" from "wrong key" beyond the wording needed
to tell an operator what to do.

`api_keys` is deliberately absent from `reproducibility_snapshot()`. That snapshot is
persisted on every scan row, and a secret in the database is a secret in every backup.

Development is unaffected: outside production, no keys means no authentication, because
requiring key management to run the thing locally is how people end up disabling it.

## Consequences

- A production deployment without `CODESENTINEL_API_KEYS` will not start. That is the
  intended behaviour and the deployment guide says so.
- Keys are flat secrets from the environment: no rotation mechanism, no per-key scoping,
  no audit trail beyond the request log. Adequate for a small number of known consumers,
  and it is written down here so nobody assumes otherwise.
- Rate limiting is a separate control and fails closed for the same reason: an endpoint
  whose whole risk is unmetered use must not become unmetered when its meter breaks.
- The frontend holds a key in the browser if it calls the API directly. `CORS_ORIGINS`
  must therefore name an exact origin — a wildcard plus a browser-held key is a credential
  any site can borrow.
