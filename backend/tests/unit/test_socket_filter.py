"""The Docker socket body filter.

This is the control ADR 0015 said was owed. Its tests are mostly attacks: each one is a
request a compromised worker would send to reach the host, and each must be refused with
a reason naming what was wrong.
"""

from __future__ import annotations

import copy

import pytest

from app.services.sandbox.socket_filter import validate

#: What the Sandbox service actually sends. Every test mutates a copy of this, so a
#: change to the real configuration that this filter would reject shows up as a failure
#: here rather than as a container that will not start.
SANDBOX_CREATE: dict[str, object] = {
    "Image": "codesentinel/analysis:0.1.0",
    "Cmd": ["radon", "cc", "-j", "--", "."],
    "Env": ["HOME=/tmp"],
    "WorkingDir": "/workspace",
    "User": "10001:10001",
    "Labels": {"codesentinel.owner": "codesentinel"},
    "NetworkDisabled": True,
    "HostConfig": {
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/var/lib/codesentinel/clones/x/repo",
                "Target": "/workspace",
                "ReadOnly": True,
            }
        ],
        "Tmpfs": {"/tmp": "size=536870912"},
        "NetworkMode": "none",
        "ReadonlyRootfs": True,
        "Memory": 2147483648,
        "CpuQuota": 100000,
        "CpuPeriod": 100000,
        "PidsLimit": 256,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "Init": True,
    },
}


def create(**host_overrides: object) -> dict[str, object]:
    body = copy.deepcopy(SANDBOX_CREATE)
    host = body["HostConfig"]
    assert isinstance(host, dict)
    host.update(host_overrides)
    return body


def test_the_sandboxs_own_request_is_allowed() -> None:
    """If this fails, the filter has locked out the thing it exists to protect."""
    assert validate("POST", "/v1.45/containers/create", SANDBOX_CREATE).allowed is True


# -- the escalations ADR 0015 said an endpoint proxy could not stop -----------


def test_a_privileged_container_is_refused() -> None:
    verdict = validate("POST", "/containers/create", create(Privileged=True))
    assert verdict.allowed is False
    assert "Privileged" in verdict.reason


def test_added_capabilities_are_refused() -> None:
    verdict = validate("POST", "/containers/create", create(CapAdd=["SYS_ADMIN"]))
    assert verdict.allowed is False
    assert "CapAdd" in verdict.reason


def test_a_host_root_bind_is_refused() -> None:
    """The classic escape: mount / and write to it."""
    verdict = validate("POST", "/containers/create", create(Binds=["/:/host"]))
    assert verdict.allowed is False
    assert "Binds" in verdict.reason


def test_device_access_is_refused() -> None:
    verdict = validate("POST", "/containers/create", create(Devices=[{"PathOnHost": "/dev/sda"}]))
    assert verdict.allowed is False


def test_the_host_pid_namespace_is_refused() -> None:
    assert validate("POST", "/containers/create", create(PidMode="host")).allowed is False


def test_sysctls_are_refused() -> None:
    verdict = validate("POST", "/containers/create", create(Sysctls={"kernel.shmmax": "1"}))
    assert verdict.allowed is False


def test_an_unknown_future_key_is_refused_by_default() -> None:
    """The reason the rule is an allowlist.

    A denylist is wrong the day Docker adds a field: the new key passes unexamined and
    nobody notices until it is used.
    """
    verdict = validate("POST", "/containers/create", create(SomeFieldDockerAddsIn2027=True))
    assert verdict.allowed is False
    assert "SomeFieldDockerAddsIn2027" in verdict.reason


# -- weakening the isolation the sandbox declares ----------------------------


def test_a_writable_mount_is_refused() -> None:
    body = create()
    host = body["HostConfig"]
    assert isinstance(host, dict)
    mounts = host["Mounts"]
    assert isinstance(mounts, list)
    mounts[0]["ReadOnly"] = False

    verdict = validate("POST", "/containers/create", body)
    assert verdict.allowed is False
    assert "read-only" in verdict.reason


def test_a_network_is_refused() -> None:
    verdict = validate("POST", "/containers/create", create(NetworkMode="bridge"))
    assert verdict.allowed is False
    assert "no network by design" in verdict.reason


def test_a_writable_root_filesystem_is_refused() -> None:
    assert validate("POST", "/containers/create", create(ReadonlyRootfs=False)).allowed is False


def test_not_dropping_all_capabilities_is_refused() -> None:
    assert validate("POST", "/containers/create", create(CapDrop=["NET_RAW"])).allowed is False


def test_disabling_seccomp_is_refused() -> None:
    verdict = validate("POST", "/containers/create", create(SecurityOpt=["seccomp=unconfined"]))
    assert verdict.allowed is False
    assert "seccomp" in verdict.reason


def test_a_create_without_a_host_config_is_refused() -> None:
    """Absent means the daemon applies its defaults: writable root, bridged network."""
    body = copy.deepcopy(SANDBOX_CREATE)
    del body["HostConfig"]
    assert validate("POST", "/containers/create", body).allowed is False


# -- endpoints ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/build"),
        ("POST", "/v1.45/images/create"),
        ("POST", "/containers/abc/exec"),
        ("POST", "/v1.45/exec/abc/start"),
        ("POST", "/networks/create"),
        ("POST", "/volumes/create"),
        ("GET", "/info"),
        ("GET", "/v1.45/images/json"),
        ("POST", "/v1.45/swarm/init"),
    ],
)
def test_endpoints_the_sandbox_does_not_use_are_refused(method: str, path: str) -> None:
    assert validate(method, path, None).allowed is False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1.45/containers/abc123/start"),
        ("POST", "/containers/abc123/wait"),
        ("POST", "/containers/abc123/kill"),
        ("GET", "/containers/abc123/logs?stdout=1"),
        ("GET", "/v1.45/containers/abc123/json"),
        ("GET", "/containers/json?all=1"),
        ("DELETE", "/v1.45/containers/abc123"),
        ("GET", "/_ping"),
        ("HEAD", "/_ping"),
    ],
)
def test_the_endpoints_the_sandbox_uses_are_allowed(method: str, path: str) -> None:
    assert validate(method, path, None).allowed is True


def test_a_query_string_does_not_defeat_route_matching() -> None:
    assert validate("POST", "/build?t=evil", None).allowed is False


def test_an_api_version_prefix_does_not_defeat_route_matching() -> None:
    """The SDK prefixes /v1.45; a filter matching only bare paths would miss every call."""
    assert validate("POST", "/v1.45/build", None).allowed is False
