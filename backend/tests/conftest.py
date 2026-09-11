"""Shared test fixtures.

Tests that need PostgreSQL are marked ``requires_db`` and **skip with an explicit reason**
when no database is reachable. They are never silently passed, and SQLite is never
substituted: the schema uses JSONB, an expression index with ``NULLS LAST``, and asyncpg
semantics, so a SQLite run would prove nothing while looking green. That is the same rule
constraint C3 applies to analysis results, applied to our own suite.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.db import reset_engine_cache
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_ENV_VAR = "CODESENTINEL_TEST_DATABASE_URL"

#: When set, an unavailable integration dependency is a failure rather than a skip.
#: CI sets it. Without this, a broken PostgreSQL service or a missing Docker daemon
#: would turn every integration test into a skip and the build would still be green --
#: acceptance evidence silently evaporating. Putting the guarantee here rather than in a
#: log-grepping CI step keeps it next to the thing it guards.
REQUIRE_INTEGRATION_ENV_VAR = "CODESENTINEL_REQUIRE_INTEGRATION"


def _unavailable(reason: str) -> NoReturn:
    """Skip because a dependency is missing -- or fail, if CI demanded it be present."""
    if os.environ.get(REQUIRE_INTEGRATION_ENV_VAR) == "1":
        pytest.fail(
            f"{REQUIRE_INTEGRATION_ENV_VAR}=1 requires this test to run, but: {reason}",
            pytrace=False,
        )
    pytest.skip(reason)


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    """Clear settings and engine caches around every test.

    Both are ``lru_cache``d for the process. Without this, a test that patches the
    environment would leak its configuration into every test that follows.
    """
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    get_settings.cache_clear()
    reset_engine_cache()


@pytest.fixture
def settings() -> Settings:
    """Default settings, read from the environment."""
    return get_settings()


@pytest.fixture
def settings_defaults() -> Settings:
    """A fresh Settings instance, for asserting values against their own source."""
    return Settings()


@pytest.fixture
def app(settings: Settings):  # type: ignore[no-untyped-def]
    """A fresh application instance per test."""
    return create_app(settings)


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    """HTTP client wired straight to the ASGI app -- no socket, no live server."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


def _test_database_url() -> str:
    """Return the test database URL or skip the test, saying exactly why.

    Checks the environment first, then ``.env`` through ``Settings`` -- the same file and
    the same variable name the application itself reads, and the one ``.env.example``
    documents. Before this, a developer could follow ``.env.example`` exactly, put
    ``CODESENTINEL_TEST_DATABASE_URL`` in ``.env``, and still watch every database test
    skip, because this function looked only at ``os.environ``. The skip reason named the
    variable, which made it look like the value was missing rather than unread.

    The environment still wins, so CI -- which exports it explicitly -- is unaffected, and
    a one-off run against a different database does not require editing a file.
    """
    url = os.environ.get(TEST_DB_ENV_VAR)
    if not url:
        configured = Settings().test_database_url
        url = str(configured) if configured else None
    if not url:
        _unavailable(
            f"{TEST_DB_ENV_VAR} is set neither in the environment nor in backend/.env, "
            "so no PostgreSQL instance is available. This test did not run; it was not "
            "verified."
        )
    return url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Session-scoped engine against the test database, with the schema migrated.

    The schema is built by running the real Alembic migrations rather than
    ``metadata.create_all``, so the migration scripts themselves are exercised. A schema
    created from metadata could pass while the migration that has to produce it in
    production is broken.
    """
    url = _test_database_url()
    # NullPool is required, not an optimisation. This fixture is session-scoped while
    # tests run on function-scoped event loops; a pooled asyncpg connection created in
    # one loop and reused in another raises "attached to a different loop". NullPool
    # opens a fresh connection per checkout, always in the loop that asks for it.
    engine = create_async_engine(url, poolclass=NullPool)

    try:
        async with engine.connect() as conn:
            await conn.rollback()
    except Exception as exc:  # noqa: BLE001 - the reason is reported in the skip message
        await engine.dispose()
        _unavailable(f"PostgreSQL at {TEST_DB_ENV_VAR} is unreachable: {exc}")

    await asyncio.to_thread(_run_migrations, url, "head")
    try:
        yield engine
    finally:
        await engine.dispose()


def _run_migrations(url: str, revision: str, *, downgrade: bool = False) -> None:
    """Run Alembic in a worker thread.

    ``alembic/env.py`` calls ``asyncio.run`` for online migrations, which raises if a loop
    is already running. Running it on a thread with no loop of its own is what makes it
    callable from an async fixture.

    ``downgrade`` selects the direction explicitly. ``command.upgrade(cfg, "base")`` is
    silently a no-op rather than a downgrade, which would make a downgrade test pass
    without reversing anything.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={url}"]})()  # type: ignore[assignment]
    if downgrade:
        command.downgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)


@pytest_asyncio.fixture
async def db_connection(db_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back.

    Rolling back rather than recreating the schema keeps tests isolated without paying to
    drop and migrate between each one.
    """
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An ORM session bound to the rolled-back connection."""
    async with AsyncSession(bind=db_connection, expire_on_commit=False) as session:
        yield session


# ---------------------------------------------------------------------------
# Docker fixtures
# ---------------------------------------------------------------------------

DOCKER_SKIP_REASON = (
    "no Docker daemon is reachable, so container isolation was NOT verified. "
    "Constraint C1 cannot be demonstrated without one."
)


@pytest.fixture(scope="session")
def docker_client() -> Iterator[Any]:
    """A live Docker client, or skip saying plainly what went unverified.

    The sandbox is a security boundary. A run of this suite that skips these tests has
    not checked that boundary at all, so the skip reason says so in those words rather
    than reading like an optional extra.
    """
    import docker
    from docker.errors import DockerException

    try:
        client = docker.from_env()
        client.ping()
    except (DockerException, OSError) as exc:
        _unavailable(f"{DOCKER_SKIP_REASON} ({exc})")

    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def analysis_image(docker_client: Any) -> str:
    """The analysis image tag, verified present.

    The sandbox has no network and cannot pull, so the image must already exist. Building
    it is the CI workflow's job; here we only refuse to pretend it is there.
    """
    from docker.errors import ImageNotFound

    image = Settings().sandbox_image
    try:
        docker_client.images.get(image)
    except ImageNotFound:
        _unavailable(
            f"analysis image {image} is not built, so the sandbox was NOT verified. "
            f"Build it with: docker build -f sandbox/Dockerfile.analysis -t {image} sandbox/"
        )
    return image


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    """A minimal directory standing in for a cloned target repository.

    Made world-readable because pytest creates tmp_path as 0700 and the sandbox runs as
    an unprivileged uid that cannot read that. Phase 3 ingestion has the same obligation
    for real clones; the sandbox refuses a tree it could not read rather than analysing
    an empty workspace and reporting a false clean.
    """
    tmp_path.chmod(0o755)
    (tmp_path / "pkg").mkdir(mode=0o755)
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "module.py").write_text("def f(x):\n    return x + 1\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Git fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def git_binary() -> str:
    """The git executable, or skip saying what went unverified.

    Ingestion is built on a real git process, so a machine without git cannot verify
    any of it. CI sets CODESENTINEL_REQUIRE_INTEGRATION=1, which turns this into a
    failure rather than a quiet skip.
    """
    git = shutil.which("git")
    if git is None:
        _unavailable(
            "no git executable is on PATH, so cloning and history mining were NOT "
            "verified. Phase 3 cannot be demonstrated without one."
        )
    return git


def _git(binary: str, repo: Path, *args: str) -> None:
    """Run a git command in ``repo``, failing loudly if it does not succeed."""
    subprocess.run(
        [binary, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
    )


@pytest.fixture
def git_repo(tmp_path: Path, git_binary: str) -> Path:
    """A small real repository: three non-merge commits across two files.

    Built with a real git process rather than a stub because the code under test parses
    real git output; a hand-written fixture would prove only that the parser matches the
    fixture. Author identity is pinned so history assertions do not depend on the
    machine's git config; timestamps are left to git, so assert on ordering rather than
    on absolute dates.
    """
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    _git(git_binary, repo, "init", "--initial-branch=main", "--quiet")
    _git(git_binary, repo, "config", "user.email", "fixture@example.com")
    _git(git_binary, repo, "config", "user.name", "Fixture Author")
    _git(git_binary, repo, "config", "commit.gpgsign", "false")

    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")

    (pkg / "module.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    _git(git_binary, repo, "add", "-A")
    _git(git_binary, repo, "commit", "-m", "feat: add module", "--quiet")

    (pkg / "module.py").write_text(
        "def f(x):\n    return x + 1\n\n\ndef g(y):\n    return y * 2\n", encoding="utf-8"
    )
    _git(git_binary, repo, "add", "-A")
    _git(git_binary, repo, "commit", "-m", "feat: add g", "--quiet")

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_module.py").write_text(
        "from pkg.module import f\n\n\ndef test_f():\n    assert f(1) == 2\n", encoding="utf-8"
    )
    _git(git_binary, repo, "add", "-A")
    _git(git_binary, repo, "commit", "-m", "test: cover f", "--quiet")

    return repo


@pytest.fixture
def git_repo_url(git_repo: Path) -> str:
    """The fixture repository as a file:// URL, for the cloner to clone."""
    return git_repo.as_uri()


@pytest.fixture
def large_git_repo(git_repo: Path, git_binary: str) -> Path:
    """The fixture repository plus a committed payload larger than a 1 MB budget.

    Incompressible bytes, because git compresses objects: a megabyte of zeroes lands as
    a few hundred bytes and the size guard would never fire.

    Committed, not merely written: a clone copies committed objects, not the working
    tree, so an uncommitted payload would leave the size test passing for the wrong
    reason -- against a clone that never contained it.
    """
    payload = git_repo / "big.bin"
    payload.write_bytes(os.urandom(3 * 1024 * 1024))
    _git(git_binary, git_repo, "add", "-A")
    _git(git_binary, git_repo, "commit", "-m", "chore: add payload", "--quiet")
    return git_repo


@pytest.fixture
def large_git_repo_url(large_git_repo: Path) -> str:
    return large_git_repo.as_uri()


class _MemoryRedis:
    """Enough Redis for the rate limiter, for tests that have no server.

    Deliberately not a no-op: it counts, so a test that submits repeatedly still meets
    the limit. Only the transport is faked.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


@pytest.fixture(autouse=True)
def _rate_limiter_backend(app) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Give every API test an in-memory rate-limit counter.

    The limiter fails closed when Redis is unreachable, which is correct in production
    and would otherwise turn every API test into a 503. The fail-closed path itself is
    tested directly in tests/unit/test_ratelimit.py.
    """
    from app.api.deps import _redis

    memory = _MemoryRedis()

    async def _override() -> Any:
        return memory

    app.dependency_overrides[_redis] = _override
    yield
    app.dependency_overrides.pop(_redis, None)


@pytest.fixture
def git_repo_with_fix(git_repo: Path, git_binary: str) -> Path:
    """The fixture repository plus a defect and a commit that fixes it.

    Built as two real commits so blame has something true to find: the bug is introduced
    on one line, and the fix replaces exactly that line. Any correct SZZ pass must name
    the introducing commit and must not name the fix itself.
    """
    module = git_repo / "pkg" / "buggy.py"
    module.write_text("def divide(x):\n    return x / 0\n", encoding="utf-8")
    _git(git_binary, git_repo, "add", "-A")
    _git(git_binary, git_repo, "commit", "-m", "feat: add divide", "--quiet")

    module.write_text("def divide(x):\n    return x / 1\n", encoding="utf-8")
    _git(git_binary, git_repo, "add", "-A")
    _git(git_binary, git_repo, "commit", "-m", "fix: crash on divide by zero", "--quiet")

    return git_repo
