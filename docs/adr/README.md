# Architecture Decision Records

One file per significant decision or deviation from the engineering brief.
Format: context, decision, consequences. Numbered sequentially, never renumbered.

| ADR | Decision |
|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions |
| [0002](0002-non-native-enums.md) | Store enums as VARCHAR with CHECK, not native PostgreSQL enums |
| [0003](0003-analysis-tools-live-in-the-sandbox-image.md) | Analysis tools are not backend runtime dependencies |
| [0004](0004-nullable-metrics.md) | Every metric column is nullable |
| [0005](0005-deferred-docker-verification.md) | Phase 1 ships without local Docker verification |
| [0006](0006-worker-docker-access.md) | Worker access to the Docker daemon is deferred to phase 2 |
| [0007](0007-ruff-and-mypy-for-first-party-code.md) | Ruff and mypy lint our code; Pylint and Bandit analyse targets |
