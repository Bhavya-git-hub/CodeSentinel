# 0020. API keys carry a name, and the name is what the logs record

**Status:** accepted — 2026-09-11

Refines [0016](0016-authentication-fails-closed.md), which recorded this gap.

## Context

ADR 0016 closed with a consequence stated plainly: keys are "flat secrets from the
environment: no rotation mechanism, no per-key scoping, no audit trail beyond the request
log." The audit-trail half is the one that bites first.

With flat keys, the most an operator can learn from the logs is that *a* valid key
submitted four hundred scans in an hour. They cannot tell which consumer, so they cannot
tell whether it is the CI integration behaving normally after a merge queue backed up, or
a leaked credential. Revocation is equally blunt: the only safe response is to rotate
every key and break every consumer, which is expensive enough that the realistic response
is to do nothing.

The obvious fix is a keys table — id, hash, name, scopes, created_at, revoked_at — with
an admin API. That is the right shape for a multi-tenant product and it is a schema, a
migration, an endpoint, and an authorisation model for the endpoint. It is a large answer
to "which key was that", and none of the rest of it is needed yet.

## Decision

A key **may** be written `name:secret`. The name is split on the first colon and bound
into the structlog context for the whole request, so every event the request goes on to
emit carries it — not just a single "authenticated" line, which would name the caller once
and leave everything the request actually did anonymous.

**The name is not a credential and is never compared.** The whole configured string is the
secret, compared with `secrets.compare_digest` exactly as before. Sending only the name
authenticates nothing, and a key with no colon keeps working unchanged — so this is not a
migration, and existing deployments are unaffected until someone renames a key.

**A key with no name gets a derived label**, `key-` plus eight hex characters of its
SHA-256. Derived rather than a prefix of the key itself: a prefix on every log line is a
head start shipped to whatever aggregator the logs go to. It is stable across processes
and replicas, which a per-process random id would not be.

The first colon separates, not the last: a generated secret can contain a colon and
splitting on the last would swallow part of it. A leading colon yields an empty name and
falls back to the digest, because an empty string in a log line identifies nobody, which
is worse than an opaque label.

## Consequences

- The logs now answer "which consumer" for every authenticated request, and revocation is
  per key with a name attached to it. That is the whole of what this buys.
- Names are visible wherever logs go. They are chosen by the operator, so a name that
  identifies a customer identifies that customer in the log pipeline.
- **Still not solved, and deliberately:** keys live in the environment as live secrets, so
  an environment leak is a credential leak. There is no rotation mechanism — rotation is
  still "edit the environment and restart" — no expiry, and no per-key scoping, so every
  key can do everything. A hashed-at-rest keys table remains the answer when any of those
  matters; this is not a step toward it so much as a cheaper answer to a narrower
  question.
- The rate limiter still buckets on a hash of the full key rather than on the name. That
  is unchanged and correct — it separates callers without putting a live credential into
  Redis — but it means a bucket cannot be matched to a name by inspection.
- The frontend's credential panel shows a stored key as `name:…`. The name is the half the
  API logs, so it is what lets a viewer match what they configured against what an
  operator can see; the secret half is never rendered at any length.
