# Design specifications

One file per phase, written before implementation and approved before code is written.

A spec says *what will be built and why it is shaped that way*. It is distinct from the
records either side of it: an [ADR](../adr/) records a single decision and outlives the
phase that made it, and a [sprint record](../sprints/) reports what was actually accepted
once the work is done. Where a spec and a sprint record disagree, the sprint record is
what happened.

Each spec is paired with an implementation plan: the spec argues the design, the plan
breaks it into tasks with their tests. Executors read both.

| Phase | Design | Plan |
|---|---|---|
| 3 — Ingestion | [spec](phase-3-ingestion.md) | [plan](phase-3-ingestion-plan.md) |
| 4 — Risk prioritisation | [spec](phase-4-risk-prioritisation.md) | — (implemented directly) |
