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
| [0015](0015-socket-proxy-filters-endpoints-not-bodies.md) | The socket proxy filters endpoints, not request bodies; body-level filtering remains owed |
| [0016](0016-authentication-fails-closed.md) | The API authenticates and refuses to start in production without keys |
| [0017](0017-socket-proxy-validates-request-bodies.md) | The socket proxy validates request bodies by allowlist, closing ADR 0015's gap |
| [0018](0018-metrics-are-opt-in-and-unauthenticated.md) | The metrics endpoint is opt-in, unauthenticated, and omits what it cannot measure |
| [0019](0019-retention-is-opt-in-and-deletes-repositories.md) | Retention is opt-in, prunes only terminal scans, and deletes emptied repositories |
| [0020](0020-api-keys-carry-a-name.md) | API keys carry a name, and the name is what the logs record — *refines [0016](0016-authentication-fails-closed.md)* |
| [0021](0021-tls-is-a-separate-overlay.md) | TLS terminates in a separate overlay, and the proxy does not hold the API key |
