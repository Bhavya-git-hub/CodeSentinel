"""The isolation settings applied to every analysis container.

These assert the *configuration* the sandbox asks Docker for, without needing a daemon,
so the security posture is checked on every run of the suite rather than only where
Docker happens to exist. The integration tests in tests/integration/test_sandbox.py then
prove the daemon actually enforces it -- neither level is sufficient alone: this one
could pass against a flag Docker ignores, and that one cannot run everywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services.sandbox import (
    OWNER_LABEL,
    OWNER_LABEL_VALUE,
    SCRATCH_PATH,
    WORKSPACE_PATH,
    Sandbox,
    SandboxConfigurationError,
)


class _StubClient:
    """Stands in for docker.DockerClient. Never contacted by these tests."""

    def close(self) -> None:
        return None


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(
        Settings(),
        source_dir=tmp_path,
        client=_StubClient(),  # type: ignore[arg-type]
        run_id="testrun",
    )


@pytest.fixture
def config(sandbox: Sandbox) -> dict[str, Any]:
    return sandbox._container_config(["echo", "hello"])


def test_container_has_no_network(config: dict[str, Any]) -> None:
    """No network at all: nothing to exfiltrate to, and no second stage to pull."""
    assert config["network_mode"] == "none"
    assert config["network_disabled"] is True


def test_source_is_mounted_read_only(config: dict[str, Any], tmp_path: Path) -> None:
    """Analysis must not be able to modify the clone that later phases mine."""
    mount = config["mounts"][0]
    assert mount["Target"] == WORKSPACE_PATH
    assert mount["Source"] == str(tmp_path.resolve())
    assert mount["ReadOnly"] is True
    assert mount["Type"] == "bind"


def test_root_filesystem_is_read_only_with_a_writable_scratch(config: dict[str, Any]) -> None:
    """Writes are possible only in tmpfs, which is discarded with the container."""
    assert config["read_only"] is True
    assert SCRATCH_PATH in config["tmpfs"]
    options = config["tmpfs"][SCRATCH_PATH]
    assert "noexec" in options
    assert "nosuid" in options


def test_container_runs_as_a_non_root_user(config: dict[str, Any]) -> None:
    """Set explicitly rather than inherited from the image.

    Relying on the image's USER alone means a rebuilt or substituted image could
    silently run as root.
    """
    assert config["user"] == "10001:10001"


def test_all_capabilities_are_dropped(config: dict[str, Any]) -> None:
    assert config["cap_drop"] == ["ALL"]


def test_privilege_escalation_is_blocked(config: dict[str, Any]) -> None:
    """Stops a setuid binary regaining what cap_drop removed."""
    assert "no-new-privileges" in config["security_opt"]


def test_memory_limit_denies_swap(settings_defaults: Settings, config: dict[str, Any]) -> None:
    """Without memswap_limit, mem_limit is a soft ceiling the container swaps past."""
    assert config["mem_limit"] == settings_defaults.sandbox_mem_limit
    assert config["memswap_limit"] == settings_defaults.sandbox_mem_limit


def test_cpu_and_pid_limits_are_applied(
    settings_defaults: Settings, config: dict[str, Any]
) -> None:
    """The PID limit is what makes a fork bomb in a target's tests a contained event."""
    assert config["cpu_quota"] == settings_defaults.sandbox_cpu_quota
    assert config["cpu_period"] == settings_defaults.sandbox_cpu_period
    assert config["pids_limit"] == settings_defaults.sandbox_pids_limit


def test_daemon_side_logs_are_bounded(config: dict[str, Any]) -> None:
    """The in-process capture bounds memory; this bounds what hits host disk."""
    log_config = config["log_config"]
    assert log_config["Config"]["max-size"] == "16m"


def test_init_process_reaps_zombies(config: dict[str, Any]) -> None:
    """Without an init, defunct children accumulate against the PID limit."""
    assert config["init"] is True


def test_containers_are_labelled_for_reaping(config: dict[str, Any]) -> None:
    """A worker killed by SIGKILL cannot run its finally; labels make orphans findable."""
    assert config["labels"][OWNER_LABEL] == OWNER_LABEL_VALUE
    assert config["labels"]["codesentinel.run_id"] == "testrun"


def test_environment_leaks_nothing_about_the_host(config: dict[str, Any]) -> None:
    """Anything the container can read, untrusted code can read."""
    environment = config["environment"]
    assert environment["HOME"] == SCRATCH_PATH
    joined = " ".join(f"{k}={v}" for k, v in environment.items()).lower()
    for forbidden in ("postgres", "redis", "password", "token", "database_url"):
        assert forbidden not in joined


def test_working_directory_is_the_mounted_workspace(config: dict[str, Any]) -> None:
    assert config["working_dir"] == WORKSPACE_PATH


def test_image_comes_from_settings(settings_defaults: Settings, config: dict[str, Any]) -> None:
    """Constraint C5: the recorded tool versions must match the image that ran."""
    assert config["image"] == settings_defaults.sandbox_image


def test_missing_source_directory_is_refused(tmp_path: Path) -> None:
    """A bind mount of a missing path would be created as an empty root-owned directory.

    The analysis would then run against nothing and report a clean result, which is worse
    than failing.
    """
    with pytest.raises(SandboxConfigurationError):
        Sandbox(
            Settings(),
            source_dir=tmp_path / "does-not-exist",
            client=_StubClient(),  # type: ignore[arg-type]
        )


def test_source_file_instead_of_directory_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "a-file.py"
    target.write_text("x = 1")
    with pytest.raises(SandboxConfigurationError):
        Sandbox(
            Settings(),
            source_dir=target,
            client=_StubClient(),  # type: ignore[arg-type]
        )
