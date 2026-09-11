---
name: codesentinel-development
description: The daily build loop for the CodeSentinel repository — code and test conventions, the exact lint/type/test gate, how to read a skipped test honestly, and when a change owes an ADR or a sprint record. Use this skill for ANY work in this repo: adding or changing a service, model, endpoint, analyser, migration, setting or Dockerfile; writing or fixing tests; running the checks; writing a commit message; recording a decision. Use it for small changes too, and even when the user says nothing about conventions, testing or ADRs — the ways work gets redone here (a hardcoded constant, a swallowed exception, a default substituted for missing data, a "passing" run whose integration tests never executed) are all silent, so they have to be prevented rather than noticed.
---

# Building CodeSentinel

Two facts about this project generate almost every rule below. Understand them and most
decisions make themselves.

**1. It runs other people's code.** CodeSentinel clones arbitrary public repositories and
executes their tooling. A target's `conftest.py` runs at pytest collection time; its
`setup.py` runs on install. Container isolation is a security boundary, not tidiness.

**2. Its entire output is "what is wrong with this code".** So a scan that silently finds
nothing is worse than a scan that fails loudly. A failure gets investigated; a clean report
gets trusted and shipped. This is why the codebase is obsessive about distinguishing
*absent* from *zero*, and *skipped* from *passed*.

When a rule here feels inconvenient, that is usually the rule doing its job. If you think it
is genuinely wrong for the case at hand, that is an ADR, not a quiet exception.

## The loop

Orient → write code → write tests → run the gate → record → commit. Work through it in
order; the gate is not the last thing you *hope* passes, it is the thing that tells you
whether you are done.

---

## 1. Orient

Before writing anything, find out where the work sits:

- **Which phase?** `docs/sprints/` holds one record per phase. The most recent one lists
  what was delivered, what was deferred, and — importantly — **obligations it placed on
  later phases**. If you are working on phase 3, phase 2's record already told you three
  things you must do.
- **Is this already decided?** `docs/adr/README.md` is a table of every decision. Skim it.
  Re-litigating a settled decision wastes the work; contradicting one silently is worse.
- **What does the existing code near this say?** Module docstrings in this repo carry the
  reasoning. `app/services/sandbox/runner.py`, `app/config.py` and `tests/conftest.py` are
  the best examples of the house style.

The repo cites a brief that is not in the tree, using a shorthand you should keep using
because the rest of the code does. As used in the code today:

| Ref | What it requires |
|---|---|
| **C1** | All analysis of a target runs inside the sandbox container. There is no host fallback. |
| **C2** | Analysis is asynchronous — the API dispatches, a worker runs it. |
| **C3** | Failures are recorded with their reason; a report says what it could not determine. |
| **C4** | Nothing is fabricated. Unresolvable things are recorded as unresolved, not dropped. |
| **C5** | Every result is reproducible: commit SHA, tool versions and config are stored with it. |

Anti-patterns referenced in code include **#1** (a "just for testing" bypass path), **#2**
(substituting `0` for missing data), **#7** (building UI before the API contract settles),
and **#9** (swallowing exceptions). Cite them the way the surrounding code does. If you need
one you have not seen used, grep first (`grep -rn "anti-pattern" --include='*.py' .`) rather
than inventing a number.

---

## 2. Write the code

The five that matter most, in full, because these are the ones that get silently wrong:

**Tunables go in `Settings`, never at the call site.** `app/config.py`, prefixed
`CODESENTINEL_`, and mirrored into `.env.example` with a comment. This is not style — C5
persists the configuration alongside each result, and a limit hardcoded in a function body
cannot be recorded, therefore cannot be reproduced.

**Missing data stays missing.** A metric that could not be computed is `None`, not `0`. A
file with no coverage data is not a file with 0% coverage — one is unknown, the other is a
bug report. Columns are nullable by default here (ADR 0004); enums carry an explicit
"failed"/"skipped" member that is distinguishable from success.

**Exceptions are caught narrowly and reported with their reason.** `BLE` is on in ruff, so
a bare `except Exception` fails lint. Where one is genuinely right, it carries a
`# noqa: BLE001` *and a comment saying where the reason surfaces*. The failure must end up
somewhere a human reads.

**Log through `structlog`, never `print`.** `T20` fails the build on `print`. Structured
events make the reason queryable instead of buried in a formatted string, which is what C3
actually demands.

**Docstrings explain why, not what.** `mypy` strict already states the types; the signature
already states the shape. Spend the docstring on the reasoning a future reader cannot
recover from the code — the race you avoided, the alternative you rejected, the constraint
you are serving. Read the docstring on `_run_migrations` in `tests/conftest.py` for the
target.

**Never weaken sandbox isolation to make something work.** There is deliberately no argument
to `Sandbox.run()` that relaxes a restriction (ADR 0009), because a caller that could would
eventually be a caller that did. If a tool needs a writable path, add a tmpfs or point an
env var at `/tmp` — do not make the root filesystem writable.

Full detail — module layout, ORM conventions, migrations, the typing rules and why `TCH` is
off — is in `references/conventions.md`. Read it before adding a model, a migration, or a
new service package.

---

## 3. Write the tests

The governing rule: **a test that did not run must never look like a test that passed.**

- Tests needing PostgreSQL are marked `requires_db`; tests needing a daemon and the built
  image are marked `requires_docker`.
- They obtain their dependency through the `conftest.py` fixtures, which call
  `_unavailable(reason)` — that skips with a reason *naming what went unverified*, or fails
  outright when `CODESENTINEL_REQUIRE_INTEGRATION=1` (CI sets it). Do not write a bare
  `pytest.skip`, and do not add a try/except that degrades to a weaker check.
- **SQLite is never substituted for PostgreSQL.** The schema uses JSONB, an expression index
  with `NULLS LAST`, and asyncpg semantics. A SQLite run proves nothing while looking green.
- Assert on the thing, not on a message. A test that asserted one specific kernel refusal
  string had to be fixed because two different, equally correct refusals exist.
- Unit and integration are complements, not alternatives: a unit test can pass against a
  flag Docker silently ignores, and integration tests cannot run where there is no daemon.
  Security-relevant behaviour gets both.

`references/testing.md` has the fixtures, the markers, and worked examples.

---

## 4. Run the gate

Run what CI runs, in CI's order. From `backend/` (on Windows the venv interpreter is
`.venv/Scripts/python`):

```bash
ruff check .
ruff format --check .
mypy app/
ruff check ../sandbox/           # easy to forget; CI does not
ruff format --check ../sandbox/
pytest -rs                       # -rs prints the reason for every skip
```

`scripts/gate.sh` in this skill runs the sequence and summarises the result honestly — use
it rather than retyping the commands.

### Reading the result

This is the step where it is easiest to mislead yourself and the user.

- **`N passed, M skipped` is not a pass when M > 0.** Say which tests skipped and what
  therefore went unverified: "53 passed, 8 skipped — the sandbox isolation tests did not
  run, so constraint C1 is unverified locally." Never round that up to "tests pass".
- **The development machine has no Docker and typically no PostgreSQL**, so locally the
  integration tests skip by design. That is expected, and it means **CI is the acceptance
  authority for anything they cover.** Local green is necessary, not sufficient.
- To prove locally that nothing is quietly skipping, set
  `CODESENTINEL_REQUIRE_INTEGRATION=1` and watch the skips become failures.
- CI has caught real defects that no local run could — a source tree the sandbox uid could
  not read, a Dockerfile heredoc that needed BuildKit, a migration test running the wrong
  direction. When work depends on a daemon or a database, the honest report is "pushed; CI
  will tell us", not a claim of completion.

---

## 5. Record the decision

**Write an ADR when you make a choice a future reader would otherwise second-guess** — a
deviation from the brief, a rejected obvious-looking approach, a constraint you are
deliberately accepting. Not for routine implementation.

The signal is simple: if while writing the code you thought *"the obvious thing here is X,
but X is wrong because…"*, that sentence is the ADR's Context section and it will be lost
otherwise. ADR 0010 exists precisely because `auto_remove=True` and `container.wait(timeout=)`
both look like the obvious answers and both are subtly wrong.

Format: `docs/adr/NNNN-kebab-title.md`, next number, never renumbered. `# NNNN. Title in a
sentence`, then `**Status:** accepted — YYYY-MM-DD`, then `## Context`, `## Decision`,
`## Consequences`. **Add the row to the table in `docs/adr/README.md`** — an ADR missing
from the index is an ADR nobody finds.

At the end of a phase, write `docs/sprints/phase-N-name.md`: scope delivered, an acceptance
table citing the **CI run number** as evidence, defects CI caught, and the obligations the
phase places on later phases. Then link it from `docs/sprints/README.md`.

`references/records.md` has both templates and the commit-message guide.

---

## 6. Commit

Conventional subject (`feat(sandbox):`, `fix(test):`, `docs:`, `ci:`, `build:`, `chore:`),
imperative, lower case, no trailing period.

**The body is the point of the commit.** Subjects say what changed; bodies say why it was
wrong before and what breaks if someone undoes it. A body in this repo typically covers:
what the failure mode actually was, why it mattered (often: what would have looked fine
while being broken), what was considered and rejected, and any obligation it creates
elsewhere. Wrap at ~88 columns.

Scope one commit to one idea. A fix and the test-fixture correction it exposes are two
commits — that is why `bdcdc48` and `a99df82` are separate.

---

## The honest-report rule

Everything above collapses into one habit: **describe the state of the work as it actually
is.** Say what ran and what did not. Say what CI must still confirm. If something is
deferred, say which phase owns it and why. The project keeps a written record of its own
unmet criteria — `docs/sprints/phase-1-foundation.md` records `docker compose up` as **not
met** rather than quietly dropping it — and a report from you that papers over a gap is
worth less than no report, because it stops anyone from looking.

## Reference files

- `references/conventions.md` — module layout, config, ORM and migrations, typing, logging,
  error design. Read before adding a model, migration or service package.
- `references/testing.md` — markers, fixtures, `_unavailable`, what to assert, worked
  examples. Read before writing tests.
- `references/records.md` — ADR template, sprint-record template, commit-message guide.
- `scripts/gate.sh` — runs the full CI-order gate and reports skips honestly.
