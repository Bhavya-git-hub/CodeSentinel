# 0003. Analysis tools are not backend runtime dependencies

**Status:** accepted — 2026-09-11

## Context

The stack table lists Pylint, Bandit, Semgrep, Radon and Coverage.py. It would be natural
to add them to `backend/pyproject.toml`.

Constraint C1 requires all analysis of target repositories to execute inside a sandboxed
container. If these tools are installed in the API and worker images, running one against
a cloned repository from the worker process becomes a single import away -- exactly the
"just for testing" path listed as anti-pattern #1. Coverage.py is the sharpest case: it
*executes the target's test suite*, and a target's `conftest.py` runs arbitrary code at
collection time.

## Decision

The analysis tools are installed only in `sandbox/Dockerfile.analysis` (phase 2). They are
not dependencies of the backend package, and the backend cannot import them.

Tool versions, required by constraint C5, are read from the sandbox image at scan time
rather than from the host environment, so the recorded version is the one that actually
produced the result.

## Consequences

- The pipeline cannot accidentally analyse a target in-process; the sandbox is the only
  path, enforced by the dependency graph rather than by discipline.
- Adapters parse tool output rather than calling tool APIs in-process. This is a real
  cost: the JSON contract of each tool becomes a compatibility surface.
- Determining tool versions requires the sandbox image to be available. A scan that
  cannot reach the image fails rather than guessing versions.
