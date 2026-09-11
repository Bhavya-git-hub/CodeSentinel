# Testing

The one rule everything else serves: **a test that did not run must never be mistaken for a
test that passed.** This project analyses other people's code for defects, so a green suite
that silently checked nothing is the exact failure mode it exists to prevent, turned inward.

## Layout and markers

```
backend/tests/
  conftest.py          all shared fixtures
  unit/                no external dependency; run everywhere, always
  integration/         need PostgreSQL or Docker; marked
```

| Marker | Means | Supplied by |
|---|---|---|
| `requires_db` | needs a reachable PostgreSQL | `CODESENTINEL_TEST_DATABASE_URL` |
| `requires_docker` | needs a daemon **and** the built analysis image | local daemon / CI |

Both are declared in `pyproject.toml`. A test that needs a dependency must be marked *and*
take the corresponding fixture — the marker documents, the fixture enforces.

## How unavailability is handled

`conftest.py` funnels every missing dependency through one helper:

```python
def _unavailable(reason: str) -> NoReturn:
    """Skip because a dependency is missing -- or fail, if CI demanded it be present."""
    if os.environ.get(REQUIRE_INTEGRATION_ENV_VAR) == "1":
        pytest.fail(f"{REQUIRE_INTEGRATION_ENV_VAR}=1 requires this test to run, but: {reason}",
                    pytrace=False)
    pytest.skip(reason)
```

So a missing dependency is a **skip with a reason that names what went unverified** during
local development, and a **failure** in CI, where `CODESENTINEL_REQUIRE_INTEGRATION=1` is
set. The guarantee lives next to the thing it guards rather than in a log-grepping CI step.

Do not write a bare `pytest.skip()`, and never add a fallback that quietly degrades to a
weaker check. Write the skip reason for someone reading CI output who was not there:

> "no Docker daemon is reachable, so container isolation was NOT verified. Constraint C1
> cannot be demonstrated without one."

Not "docker not available".

## Fixtures available

| Fixture | Gives you |
|---|---|
| `settings` | `Settings` from the environment |
| `settings_defaults` | a fresh `Settings()`, for asserting defaults against their own source |
| `app` | a fresh application instance |
| `client` | `AsyncClient` wired to the ASGI app — no socket, no live server |
| `db_engine` | session-scoped engine, schema built by **running the real migrations** |
| `db_connection` | connection in a transaction that is always rolled back |
| `db_session` | `AsyncSession` bound to that connection |
| `docker_client` | live Docker client, or a skip that says what went unverified |
| `analysis_image` | the image tag, verified present (the sandbox cannot pull — no network) |
| `source_tree` | a minimal world-readable stand-in for a cloned repository |

`_reset_caches` is autouse: it clears the settings and engine `lru_cache`s around every
test, so a test that patches the environment cannot leak configuration into the next one.

Two fixture details that look like style but are load-bearing:

- `db_engine` uses `NullPool` **because it must**. The fixture is session-scoped while tests
  run on function-scoped event loops; a pooled asyncpg connection created in one loop and
  reused in another raises "attached to a different loop".
- `source_tree` does `tmp_path.chmod(0o755)` because pytest creates `tmp_path` as `0700` and
  the sandbox runs as uid 10001. Without it the container sees an empty workspace — the
  fixture would not be representative of a real clone.

## Rules

**Never substitute SQLite for PostgreSQL.** The schema uses JSONB, an expression index with
`NULLS LAST`, and asyncpg semantics. A SQLite run proves nothing while looking green. This
is C3's rule about analysis results, applied to our own suite.

**Exercise the migrations, not `metadata.create_all`.** A schema built from metadata can
pass while the migration that has to produce it in production is broken.

**Test direction explicitly.** `command.upgrade(cfg, "base")` is silently a no-op rather
than a downgrade — which would make a downgrade test pass without reversing anything. Pass
the direction, do not infer it.

**Assert the behaviour, not one phrasing of it.** A read-only mount and a uid mismatch
produce different kernel messages and both are correct refusals; the test that named one of
them had to be fixed. Assert that the write failed, not how it said so.

**Security-relevant behaviour gets both levels.** Unit tests over the requested container
configuration run everywhere but can pass against a flag Docker silently ignores.
Integration tests ask a real daemon to actually stop something but cannot run where there
is no daemon. Neither is sufficient alone.

**Prove the mechanism, not the environment.** Network isolation is asserted on the
container's own interface list being exactly `["lo"]` — reaching for an external host would
test the CI runner's connectivity instead. Likewise the timeout test asserts on wall-clock
duration *and* that no container survives, because that is what separates killing the
container from abandoning the wait.

## Running

From `backend/` (Windows: `.venv/Scripts/python -m pytest`):

```bash
pytest -rs                                   # -rs prints every skip reason
pytest tests/unit -q                          # fast loop while iterating
pytest --cov=app --cov-report=term-missing    # what CI measures
CODESENTINEL_REQUIRE_INTEGRATION=1 pytest -rs # prove nothing is quietly skipping
```

`filterwarnings = ["error::DeprecationWarning"]` is set, so a deprecation in a dependency
fails the suite. That is intentional — fix it or scope an ignore with a comment.

## Reporting a run

State passes **and** skips, and say what the skips leave unverified:

> 93 passed, 0 skipped — every `requires_db` and `requires_docker` test ran.

> 53 passed, 8 skipped — the sandbox tests did not run (no local daemon), so constraint C1
> is unverified here; CI is the acceptance evidence for it.

Never compress the second one into "tests pass".
