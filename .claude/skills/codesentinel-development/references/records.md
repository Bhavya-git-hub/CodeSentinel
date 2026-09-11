# Records: ADRs, commits, sprint records

Three artefacts, one purpose: make the reasoning survive the person who had it. The code
shows what was built; these say why it is that shape and what breaks if someone changes it
back.

---

## ADRs

### When to write one

Write an ADR when a future reader would otherwise second-guess the choice:

- a deviation from the brief, or a constraint deliberately accepted
- an obvious-looking approach that is wrong for a non-obvious reason
- a decision deferred to a later phase (say what has to be decided, and by whom)
- a rule you are making unconditional, so nobody relaxes it later

The reliable signal: while writing the code you thought *"the obvious thing here is X, but
X is wrong because…"*. That sentence is the Context section, and it is lost otherwise.
ADR 0010 exists because `auto_remove=True` and `container.wait(timeout=N)` both look like
the obvious answers and both are subtly wrong — without the record, the next person
"simplifies" the code straight back into the bug.

Do **not** write one for routine implementation. Ten ADRs that each decide something beat
thirty that narrate work.

### Format

`docs/adr/NNNN-kebab-case-title.md` — next number, sequential, **never renumbered**.

```markdown
# NNNN. The decision, stated as a sentence

**Status:** accepted — YYYY-MM-DD

## Context

The forces. What made this a decision rather than a default: the constraint in play, the
approach that looks obvious, and precisely why it fails. Name the concrete case that will
tempt someone later ("Phase 5 will make that temptation concrete: most target repositories
cannot install their dependencies without network access").

## Decision

What was decided, in the active voice. A table works well when the decision is a set of
things rather than one thing — see ADR 0009's restriction table, which pairs each
restriction with what it stops.

## Consequences

What follows — including the costs. Obligations this places on later phases, what it rules
out, what stays open. This section is what makes an ADR useful rather than decorative.
```

**Then add the row to the table in `docs/adr/README.md`.** An ADR missing from the index is
an ADR nobody finds.

Statuses: `accepted`, `superseded by NNNN`, `amended by NNNN`. A decision that turns out
wrong is corrected by a new record that says so — ADR 0005 was corrected in the phase 2
sprint record, not edited into looking right.

---

## Commit messages

### Subject

`type(scope): imperative summary` — lower case, no trailing period, ~72 chars.

Types in use: `feat`, `fix`, `test`, `docs`, `ci`, `build`, `chore`. Scopes are the area
touched: `sandbox`, `test`, `db`, `api`, `models`, `config`, `workers`, `build`.

### Body

The body is the point. Subjects say what changed; bodies say why the old state was wrong and
what breaks if someone undoes this. Wrap at ~88 columns. Cover, in whatever order reads
best:

1. **What the failure actually was** — concretely, including how it was found ("CI found
   this the first time the sandbox ran against a real daemon").
2. **Why it mattered** — usually: what would have looked fine while being broken. This is
   the sentence that stops someone reverting you.
3. **What was considered and rejected** — and why. "Checked rather than repaired: silently
   chmod-ing a host directory is a surprising side effect."
4. **What it obliges elsewhere** — a requirement it places on a later phase, an assertion it
   relaxed, a follow-up left open.

Worked example (`bdcdc48`):

```
fix(sandbox): refuse a source tree the sandbox user cannot read

CI found this the first time the sandbox ran against a real daemon: the container runs
as an unprivileged uid that will never match the host user which made the clone, so a
source tree that is not world-readable is invisible inside the container.

The failure mode is the dangerous kind. Every analyser would see an empty workspace, find
nothing, and the scan would look perfectly healthy -- a clean report for a repository
nobody actually analysed. For a tool whose entire output is 'what is wrong with this
code', silently reporting nothing is the worst available answer.

The sandbox now checks the mount is readable and raises SandboxConfigurationError naming
the mode and the fix. Checked rather than repaired: silently chmod-ing a host directory
is a surprising side effect, and the obligation belongs to whatever created the clone --
which makes this a requirement on phase 3 ingestion.
```

### Scope

One commit, one idea. The fix above and the test-fixture correction it exposed are two
commits (`bdcdc48`, `a99df82`) because they are two ideas — and the second commit's body
gets to say "the guard was right; the fixture was not representative", which a combined
commit would have buried.

---

## Sprint records

One file per phase: `docs/sprints/phase-N-name.md`, linked from `docs/sprints/README.md`.
Written when the phase closes.

```markdown
# Phase N — Name

## Scope delivered

Bulleted, by artefact, each with the one thing that makes it non-obvious.

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| ... | met / **not met** | CI run **NNNNNNNN**: 93 passed, **0 skipped** |

Evidence names a CI run number and the pass/skip counts. "It works locally" is not
evidence for anything requiring a daemon or a database. A criterion that is not met is
recorded as **not met**, with its own section explaining why and what would satisfy it.

Follow the table with a paragraph on anything subtle about *how* a criterion was proved —
e.g. asserting on the container's own interface list rather than reaching for an external
host, so the test proves isolation rather than the runner's connectivity.

## Defects CI caught

Numbered, each saying what the defect was and why it mattered. This section is how the
project learns which classes of bug local runs cannot find.

## Obligations this places on later phases

The most valuable section. Anything a later phase must now do or must not do, with the
ADR or code that establishes it. Phase 3 starts by reading this.

## Still not met from phase N-1

Carried-forward gaps, restated rather than quietly dropped.
```

If an earlier record turns out to be wrong, add a **Correction to ADR NNNN** section saying
what was claimed, what is actually true, and which part of the original still stands. Phase
2's record does this for ADR 0005's "hard-blocked" claim. Corrections are additive; the
original record is not rewritten to look prescient.
