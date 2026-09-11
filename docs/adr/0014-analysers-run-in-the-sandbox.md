# 0014. Analysers run in the sandbox, and the Docker requirement arrives in phase 4

**Status:** accepted — 2026-09-11

Amends [ADR 0013](0013-worker-docker-access.md).

## Context

Radon reads source files and imports nothing from them. It does not execute the target's
code, so on a strict reading of ADR 0011 — where the C1 boundary is *executing* target
code rather than reading its bytes — Radon could legitimately run on the host, exactly as
the file inventory does.

Running it on the host would also be markedly more convenient: no image, no daemon, no
container per scan, and phase 4 would be verifiable on a development machine.

That is the argument, and it is the reason this ADR exists. The problem is not Radon. The
problem is that accepting it establishes *per-tool risk assessment* as the way this
question gets answered. The next tool is Pylint, which loads plugins from the target's
configuration. The one after is coverage, which imports the target's code outright. Each
is judged on its own merits by whoever is adding it, under deadline, and the boundary
moves one tool at a time until it is somewhere nobody chose.

ADR 0013 also predicted the wrong phase. It reasoned that phase 3 ran no containers so the
worker needed no daemon, and put the socket-proxy work in phase 5 with the analysers.
Analysers are phase 4.

## Decision

**Every analyser runs inside the sandbox**, without exception and without a per-tool
exemption, even when the tool plainly does not execute target code. The rule is
categorical precisely so it cannot be relitigated per tool.

Host-side computation is limited to data this system already holds. Churn is computed
from our own `file_changes` rows, so nothing a target contains can influence it beyond the
line counts phase 3 recorded; that is a different category from reading the target's
files, and it stays on the host.

**The filtering socket proxy requirement moves from phase 5 to phase 4.** The decision
ADR 0013 made — a filtering proxy exposing only container create/start/wait/logs/remove,
never a raw socket mount — is unchanged and is not reopened here. Only its phase is wrong.

`analysis_enabled` exists so a deployment with no daemon can still ingest repositories.
It defaults to true, is recorded in the reproducibility snapshot, and a scan that ran with
it false records `PARTIAL` with the reason — it never yields a scan that looks like one
which analysed the code and found it uniformly simple.

## Consequences

- Phase 4 cannot be verified on a machine without Docker. Its Radon integration tests skip
  with a reason, and CI is the acceptance authority for them — the same position phase 2
  was in, for the same reason.
- Adding an analyser is now a closed question: it goes in the image and runs in the
  sandbox. There is no discussion to have and no exemption to argue for.
- `analysis_enabled=false` is a supported deployment, not a bypass. It cannot be reached
  accidentally, it is recorded in the scan's own configuration, and it downgrades the scan
  to `PARTIAL` rather than hiding the gap — which is what separates it from anti-pattern
  #1.
- The phase 5 obligations from ADR 0013 and ADR 0010 stand and are now overdue rather than
  upcoming: the socket proxy, and scoping `reap_orphans()` to the worker's own identity
  before concurrent scans exist.
