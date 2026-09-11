# 0011. Cloning runs on the host under an unconditional hardening set

**Status:** accepted — 2026-09-11

## Context

Constraint C1 says all analysis of a target runs inside the sandbox container, with no
host fallback. ADR 0009 gives that container no network and no way to ask for one. The two
together produce a contradiction the moment ingestion exists: the sandbox cannot clone,
because cloning needs the network it is defined not to have.

Something has to give, and the choices are narrow. Giving the sandbox a network for the
duration of a clone reopens exactly the hole ADR 0009 closed, and "only during the clone"
is a distinction the kernel does not enforce. Adding a second, network-enabled container
type that is trusted to only fetch bytes means maintaining two isolation postures and
hoping nobody blurs them. Or the clone runs on the host.

Running it on the host means `git` executes on our machine against a URL an untrusted
caller chose. That is a real exposure and not a theoretical one: `ext::` URLs hand the
remainder of the string to a shell, a repository's own hooks can execute during clone,
submodules pull further content the size budget never sees, and a symlink in the tree can
point anywhere on the host.

## Decision

The C1 boundary is **executing the target's code**, not reading the target's bytes.

Cloning and file inventory run on the host. Anything that *runs* target tooling -- its
test suite, its `setup.py`, its `conftest.py`, a linter loading its plugins -- still runs
in the sandbox, and no phase may relax that.

The clone runs under a hardening set applied unconditionally, in the spirit of ADR 0009:
there is no argument to `clone_repository` that weakens any of it.

| Control | What it stops |
|---|---|
| URL validation before any process starts | `ext::` command execution, scp-like syntax, argument injection via a leading `-` |
| `protocol.allow=never` plus an explicit allowlist | Every exotic transport, including ones added by a future git |
| `--no-recurse-submodules` | Pulling further untrusted content outside the size budget |
| `core.hooksPath` at a non-existent path | The repository's own hooks executing during the clone |
| `GIT_TERMINAL_PROMPT=0`, empty `GIT_ASKPASS`, empty `credential.helper` | Hanging on a credential prompt, and leaking host credentials |
| `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` at devnull | A host `insteadOf` rule silently rewriting the validated URL |
| `core.symlinks=false` | Symlinks escaping the clone root |
| Size sampling, then terminate → kill → wait | Filling the host disk |
| `clone_timeout_seconds` on the same wait | A stalled remote holding a worker slot indefinitely |
| `chmod o+rX` on success | The sandbox being unable to read what we cloned |

The transport allowlist is a setting rather than a constant, because tests must clone from
a local path and the alternative is a "just for testing" branch inside the cloner
(anti-pattern #1). Because the allowlist is in `reproducibility_snapshot()`, a scan that
ran under a relaxed one says so in its own record.

Validation is applied twice -- once in our own code, once via git's `protocol.allow` --
and that duplication is deliberate. Driving the clone process directly bypasses
GitPython's `check_unsafe_protocols` screen, so the explicit check replaces it rather than
supplementing it; the git-level config then covers anything our parser fails to anticipate.

## Consequences

- Later phases that parse target *content* on the host (an AST walk, a manifest read)
  inherit this justification. Later phases that *run* target tooling do not, and must use
  the sandbox.
- The host now runs a process against attacker-chosen input. That is accepted, bounded by
  the table above, and is the reason the cloner owns its own `Popen` rather than delegating
  to a library whose abort path does not work.
- `chmod o+rX` is a hard obligation, not a convenience. The sandbox runs as uid 10001,
  which never matches the host user that made the clone; a tree that is not world-readable
  is an empty workspace inside the container, and every analyser would report a clean
  result for a repository nobody read. The cloner applies it and the sandbox independently
  refuses a tree it cannot read, so the guarantee is asserted at both ends.
- The size guard is a ceiling with overshoot, not a hard cap: the real bound is
  `limit + (interval × transfer rate)`. The interval is configuration so the overshoot is
  tunable and recorded rather than implicit.
