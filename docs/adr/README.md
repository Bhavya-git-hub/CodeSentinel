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
| [0006](0006-worker-docker-access.md) | Worker access to the Docker daemon is deferred to phase 2 — *superseded by [0013](0013-worker-docker-access.md)* |
| [0007](0007-ruff-and-mypy-for-first-party-code.md) | Ruff and mypy lint our code; Pylint and Bandit analyse targets |
| [0008](0008-dependency-pinning.md) | Backend dependencies resolve from pyproject, not a committed lock |
| [0009](0009-sandbox-isolation-is-not-configurable.md) | Sandbox isolation is applied as a set, with no opt-out |
| [0010](0010-container-cleanup-and-timeout-handling.md) | Containers are removed in a `finally`; timeouts kill rather than abandon |
| [0011](0011-host-clone-hardening.md) | Cloning runs on the host under an unconditional hardening set |
| [0012](0012-worker-event-loop-per-task.md) | Workers run an async body per task under `asyncio.run`, with `NullPool` |
| [0013](0013-worker-docker-access.md) | The phase 3 worker gets no Docker access; a filtering socket proxy is chosen for phase 5 |
| [0014](0014-analysers-run-in-the-sandbox.md) | Analysers run in the sandbox without per-tool exemption; the Docker requirement arrives in phase 4 |
