"""Container isolation, verified against a real Docker daemon.

Marked ``requires_docker``. These are the acceptance evidence for constraint C1, and none
of them can be faked: each one asks the daemon to actually stop something.

When no daemon is reachable they skip with a reason that says the boundary went
unverified, and CI fails if that happens there.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import pytest
from docker.errors import DockerException

from app.config import Settings
from app.services.sandbox import (
    OWNER_LABEL,
    OWNER_LABEL_VALUE,
    SCRATCH_PATH,
    WORKSPACE_PATH,
    Sandbox,
    SandboxImageMissingError,
    SandboxOutcome,
)

pytestmark = pytest.mark.requires_docker


@pytest.fixture
def sandbox(analysis_image: str, docker_client: Any, source_tree: Path) -> Any:
    with Sandbox(Settings(), source_dir=source_tree, client=docker_client) as box:
        yield box


def _our_containers(client: Any) -> list[Any]:
    return client.containers.list(all=True, filters={"label": f"{OWNER_LABEL}={OWNER_LABEL_VALUE}"})


# -- the three acceptance criteria ------------------------------------------------


def test_the_container_has_no_network_interfaces(sandbox: Sandbox) -> None:
    """Acceptance: a container attempting a network call fails.

    Asserted on the interface list rather than by reaching for an external host, so the
    test proves isolation instead of proving the CI runner's connectivity.
    """
    result = sandbox.run(
        [
            "python",
            "-c",
            "import socket, json; print(json.dumps([n for _, n in socket.if_nameindex()]))",
        ],
        timeout=60,
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == ["lo"]


def test_an_outbound_connection_fails(sandbox: Sandbox) -> None:
    """The same guarantee from the attacker's direction: the call itself must fail."""
    result = sandbox.run(
        [
            "python",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), timeout=5)",
        ],
        timeout=60,
    )
    assert result.exit_code != 0
    assert "unreachable" in result.stderr.lower() or "error" in result.stderr.lower()


def test_dns_resolution_fails(sandbox: Sandbox) -> None:
    """No DNS either -- resolution alone would already be an exfiltration channel."""
    result = sandbox.run(
        ["python", "-c", "import socket; socket.gethostbyname('example.com')"], timeout=60
    )
    assert result.exit_code != 0


def test_an_infinite_loop_is_killed_at_the_timeout(sandbox: Sandbox) -> None:
    """Acceptance: an infinite-loop command is killed at the timeout.

    The duration bound is the real assertion. Abandoning the wait without killing would
    also return promptly, while leaving a container spinning a host core forever.
    """
    result = sandbox.run(["python", "-c", "while True: pass"], timeout=5)

    assert result.outcome is SandboxOutcome.TIMED_OUT
    assert result.timed_out
    assert result.exit_code is None, "a killed container has no exit code to report"
    assert 5 <= result.duration_seconds < 60
    assert result.describe_failure() is not None


def test_the_timed_out_container_is_actually_dead(sandbox: Sandbox, docker_client: Any) -> None:
    """The kill must reach the process, not just end our request."""
    sandbox.run(["python", "-c", "while True: pass"], timeout=5)
    running = docker_client.containers.list(
        filters={"label": f"{OWNER_LABEL}={OWNER_LABEL_VALUE}", "status": "running"}
    )
    assert running == []


def test_no_containers_remain_after_a_failed_run(sandbox: Sandbox, docker_client: Any) -> None:
    """Acceptance: no containers remain after a failed run."""
    result = sandbox.run(["python", "-c", "import sys; sys.exit(3)"], timeout=60)
    assert result.exit_code == 3
    assert _our_containers(docker_client) == []


def test_no_containers_remain_after_a_timeout(sandbox: Sandbox, docker_client: Any) -> None:
    sandbox.run(["python", "-c", "while True: pass"], timeout=5)
    assert _our_containers(docker_client) == []


def test_no_containers_remain_when_the_caller_raises(
    sandbox: Sandbox, docker_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The removal is in a finally, so an exception mid-run must not leak a container.

    This is the case auto_remove would not cover and that a try/except would miss.
    """

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated failure while capturing output")

    monkeypatch.setattr(Sandbox, "_capture", _explode)

    with pytest.raises(RuntimeError):
        sandbox.run(["python", "-c", "print('hi')"], timeout=60)

    assert _our_containers(docker_client) == []


# -- the rest of the isolation ----------------------------------------------------


def test_the_source_mount_is_read_only(sandbox: Sandbox) -> None:
    """Analysis must not modify the clone that phases 4 and 8 mine for history."""
    result = sandbox.run(
        [
            "python",
            "-c",
            f"open('{WORKSPACE_PATH}/pkg/injected.py', 'w').write('x')",
        ],
        timeout=60,
    )
    assert result.exit_code != 0
    # Either refusal is correct: the kernel may report the read-only mount or, when the
    # host owner differs from the sandbox uid, a plain permission denial. Asserting on
    # one specific message would make the test depend on which one happens to win.
    stderr = result.stderr.lower()
    assert "read-only" in stderr or "permission denied" in stderr


def test_the_source_is_actually_visible(sandbox: Sandbox) -> None:
    """The mount has to work, or every other assertion here is vacuous."""
    result = sandbox.run(["cat", f"{WORKSPACE_PATH}/pkg/module.py"], timeout=60)
    assert result.exit_code == 0
    assert "def f(x)" in result.stdout


def test_the_host_cannot_be_modified_through_the_mount(sandbox: Sandbox, source_tree: Path) -> None:
    """Belt and braces: confirm on the host side that nothing was written."""
    sandbox.run(
        ["python", "-c", f"open('{WORKSPACE_PATH}/escape.txt', 'w').write('x')"], timeout=60
    )
    assert not (source_tree / "escape.txt").exists()


def test_the_root_filesystem_is_read_only(sandbox: Sandbox) -> None:
    result = sandbox.run(
        ["python", "-c", "open('/usr/local/injected', 'w').write('x')"], timeout=60
    )
    assert result.exit_code != 0


def test_scratch_space_is_writable(sandbox: Sandbox) -> None:
    """The tools need somewhere to write, or pylint and semgrep fail on their caches."""
    result = sandbox.run(
        [
            "python",
            "-c",
            f"p='{SCRATCH_PATH}/probe'; open(p,'w').write('ok'); print(open(p).read())",
        ],
        timeout=60,
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"


def test_the_container_does_not_run_as_root(sandbox: Sandbox) -> None:
    result = sandbox.run(["python", "-c", "import os; print(os.getuid())"], timeout=60)
    assert result.exit_code == 0
    assert result.stdout.strip() == "10001"


def test_capabilities_are_dropped(sandbox: Sandbox, docker_client: Any) -> None:
    """Verified against the daemon's own view of the container, not our request."""
    config = Sandbox(
        Settings(), source_dir=Path.cwd(), client=docker_client, run_id="capcheck"
    )._container_config(["true"])
    container = docker_client.containers.create(**config)
    try:
        container.reload()
        host_config = container.attrs["HostConfig"]
        assert host_config["CapDrop"] == ["ALL"]
        assert "no-new-privileges" in host_config["SecurityOpt"]
        assert host_config["NetworkMode"] == "none"
        assert host_config["ReadonlyRootfs"] is True
        assert host_config["PidsLimit"] == Settings().sandbox_pids_limit
    finally:
        container.remove(force=True)


# -- output handling ---------------------------------------------------------------


def test_a_nonzero_exit_is_a_result_not_an_exception(sandbox: Sandbox) -> None:
    """Pylint exits non-zero precisely when it finds issues.

    Treating that as a sandbox failure would report every repository with lint warnings
    as an analyser crash.
    """
    result = sandbox.run(["python", "-c", "import sys; sys.exit(7)"], timeout=60)
    assert result.outcome is SandboxOutcome.COMPLETED
    assert result.exit_code == 7
    assert result.describe_failure() is None


def test_stdout_and_stderr_are_captured_separately(sandbox: Sandbox) -> None:
    result = sandbox.run(
        [
            "python",
            "-c",
            "import sys; sys.stdout.write('OUT'); sys.stderr.write('ERR')",
        ],
        timeout=60,
    )
    assert "OUT" in result.stdout
    assert "ERR" not in result.stdout
    assert "ERR" in result.stderr


def test_unbounded_output_is_capped_and_reported(
    docker_client: Any, analysis_image: str, source_tree: Path
) -> None:
    """A target printing in a loop must not be handed into the worker's memory.

    The truncation flag matters as much as the cap: a truncated result silently presented
    as complete would let an analyser parse a half-written JSON document.
    """
    settings = Settings(sandbox_max_output_bytes=4096)
    with Sandbox(settings, source_dir=source_tree, client=docker_client) as box:
        result = box.run(
            ["python", "-c", "print('A' * 200, flush=True)\nprint('B' * 500000)"],
            timeout=60,
        )

    assert result.stdout_truncated
    assert result.truncated
    assert len(result.stdout.encode()) <= 4096


def test_output_below_the_cap_is_not_marked_truncated(sandbox: Sandbox) -> None:
    result = sandbox.run(["python", "-c", "print('small')"], timeout=60)
    assert not result.truncated
    assert result.stdout.strip() == "small"


# -- image metadata and housekeeping ------------------------------------------------


def test_tool_versions_come_from_the_image(sandbox: Sandbox) -> None:
    """Constraint C5: the recorded versions must be the ones that produced the result.

    Read from inside the image rather than the host, which does not have these tools
    installed at all (ADR 0003).
    """
    versions = sandbox.tool_versions()
    assert set(versions) >= {"pylint", "bandit", "semgrep", "radon", "coverage", "python"}
    assert versions["python"].startswith("3.11")
    for tool, version in versions.items():
        assert version and version[0].isdigit(), f"{tool} reported {version!r}"


def test_a_missing_image_is_reported_not_worked_around(
    docker_client: Any, source_tree: Path
) -> None:
    """The sandbox has no network and cannot pull, so this must fail loudly.

    Silently substituting another image would change which tool versions produced a
    result, breaking C5 without any visible sign.
    """
    settings = Settings(sandbox_image="codesentinel/definitely-not-built:0.0.0")
    with Sandbox(settings, source_dir=source_tree, client=docker_client) as box:  # noqa: SIM117
        with pytest.raises(SandboxImageMissingError):
            box.run(["true"], timeout=30)


def test_reap_orphans_removes_leftover_containers(sandbox: Sandbox, docker_client: Any) -> None:
    """Covers the worker killed by SIGKILL, which never runs its finally."""
    config = sandbox._container_config(["sleep", "300"])
    orphan = docker_client.containers.create(**config)
    try:
        assert len(_our_containers(docker_client)) == 1
        assert sandbox.reap_orphans() == 1
        assert _our_containers(docker_client) == []
    finally:
        # Already reaped is the expected path; this only covers the assertion failing.
        with contextlib.suppress(DockerException):
            orphan.remove(force=True)


def test_each_run_uses_a_fresh_container(sandbox: Sandbox) -> None:
    """State must not carry between analyses; one throwaway container per run."""
    first = sandbox.run(
        ["python", "-c", f"open('{SCRATCH_PATH}/marker','w').write('1')"], timeout=60
    )
    assert first.exit_code == 0

    second = sandbox.run(
        [
            "python",
            "-c",
            f"import os; print('present' if os.path.exists('{SCRATCH_PATH}/marker') else 'absent')",
        ],
        timeout=60,
    )
    assert second.stdout.strip() == "absent"
