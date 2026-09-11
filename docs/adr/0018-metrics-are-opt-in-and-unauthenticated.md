# 0018. The metrics endpoint is opt-in, unauthenticated, and omits what it cannot measure

**Status:** accepted — 2026-09-11

## Context

`docs/DEPLOYMENT.md` listed "no metrics endpoint" among the things this system does not
do. Adding one runs into a conflict the rest of the API does not have.

Every `/api/v1` route requires `X-API-Key`. A Prometheus scraper has no key to present
and no place to put one — scrape configs can carry a bearer token, but the whole reason
this service authenticates is that it clones and analyses attacker-chosen URLs, and a key
distributed to a monitoring system is a key in a monitoring system's config repository.
So the endpoint either gets its own credential, which is another secret to rotate and a
second authentication path to keep correct, or it gets none.

The second problem is worse and is specific to this project. Metrics are aggregates
computed from the database. If the database is unreachable, a naive implementation
reports `codesentinel_scans{status="succeeded"} 0`. That is anti-pattern #2 with a graph
attached to it: on a dashboard, an unknown value rendered as zero draws a confident flat
line along the bottom, which is indistinguishable from a healthy system that has simply
had a quiet hour — and much harder to argue with than a bare number, because it looks
like evidence.

## Decision

**Off by default.** `CODESENTINEL_METRICS_ENABLED=false` unless an operator sets it. The
route is *not registered* when disabled rather than registered and answering 404, because
a 404 from a disabled endpoint and a 404 from a misrouted scrape are the same response to
someone debugging a scrape config.

**Unauthenticated when enabled**, like the health probes and for the same reason. The
protection is that it does not exist unless asked for, and that it carries nothing worth
having: aggregate counts only, with no repository URL, no key, no name of who submitted
what. A test asserts that no `://` appears anywhere in the exposition, because a target's
clone URL is the one genuinely sensitive thing an aggregate could leak — it names what
this instance was pointed at.

**A value it cannot compute is absent, never zero.** On a database error the
`codesentinel_scans` and `codesentinel_repositories` series are omitted entirely and
`codesentinel_database_reachable` goes to 0. Prometheus treats a missing series as
missing: a dashboard draws a gap, `absent()` alerts fire, and nothing reads as a
measurement that was never taken.

The endpoint still returns **200** in that state. A 5xx would discard the in-process
request counters, which are perfectly good, and would make a live target look down when
it is up and serving.

The exposition text is written by hand rather than taken from `prometheus_client`. For
four series of counters and gauges the format is a dozen lines; every label value comes
from a closed set, so no escaping case can arise; and the alternative is a dependency
plus its multiprocess-registry machinery, which exists for exactly the deployment shape
this does not have.

Request counters are labelled with the **route template**, not the request path.
`/api/v1/scans/{scan_id}` is one series; the raw path is one series per scan id, which is
an unbounded label set and is how a metrics endpoint kills the process it is describing.
Unmatched paths collapse into a single `<unmatched>` bucket, because 404 probing is the
ordinary way that label set gets filled in from outside.

## Consequences

- An operator who enables this must keep it off the public internet. The TLS overlay
  deliberately does not proxy `/metrics`, and the Caddyfile says why at the point where
  someone would add it.
- Series appear and disappear as statuses occur. A status with no scans produces no row
  from PostgreSQL, and inventing the missing rows would be inventing measurements — so
  dashboards must tolerate a missing series, which they must anyway for the outage case.
- There is no scan-duration histogram and no queue-depth gauge. Both are worth having;
  neither is here, and that is a gap rather than a decision that they are unnecessary.
- The counters are per process and reset on restart, which is what `counter` means. With
  two API replicas, Prometheus sums them; nothing in the application aggregates across
  replicas.
