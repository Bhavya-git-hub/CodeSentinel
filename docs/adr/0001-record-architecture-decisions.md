# 0001. Record architecture decisions

**Status:** accepted — 2026-09-11

## Context

The engineering brief prescribes a specific stack, data model and phase order, and
requires an ADR for any significant decision or deviation. Several of its constraints
(C1-C5) are correctness requirements rather than preferences, so a decision that touches
one of them needs its reasoning preserved, not just its outcome.

## Decision

Every significant decision, and every deviation from the brief, gets a numbered ADR in
`docs/adr/`. ADRs are append-only: superseded ones are marked superseded rather than
edited or deleted.

## Consequences

A reviewer can tell the difference between a deliberate deviation and an oversight. The
cost is one short file per decision.
