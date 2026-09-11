"""Validating Docker API requests before they reach the daemon.

ADR 0015 recorded what an off-the-shelf endpoint proxy cannot do: it allows or denies by
path and method, and `Privileged`, `Binds`, `CapAdd` and `Devices` all live inside the
body of `POST /containers/create` -- a request the sandbox cannot work without. So a
worker that had been taken over could still ask for a privileged container mounting the
host root, and the proxy would forward it.

This closes that. It is a **pure function**: method, path and decoded body in, a verdict
out. No sockets, no I/O, no daemon. That is deliberate -- ADR 0013 justified the proxy on
the grounds that it is "small enough to audit", and a validator entangled with transport
is not auditable, it is merely reviewed.

The design rule is an **allowlist of HostConfig keys with constrained values**, never a
denylist of dangerous ones. A denylist is wrong the day Docker adds a field: the new key
passes unexamined and nobody notices until it is used. An allowlist fails closed on
exactly that case -- an unknown key is refused, and the refusal names it, so adding a
legitimate one is a deliberate edit here rather than an accident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether a request may proceed, and why not when it may not."""

    allowed: bool
    reason: str = ""


ALLOW = Verdict(True)


def deny(reason: str) -> Verdict:
    return Verdict(False, reason)


#: Endpoints the Sandbox service actually uses. Everything else -- build, images, exec,
#: networks, volumes, swarm, the daemon's own info -- is refused outright.
ALLOWED_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/(?:v[\d.]+/)?containers/create$")),
    ("POST", re.compile(r"^/(?:v[\d.]+/)?containers/[a-zA-Z0-9_.-]+/start$")),
    ("POST", re.compile(r"^/(?:v[\d.]+/)?containers/[a-zA-Z0-9_.-]+/wait$")),
    ("POST", re.compile(r"^/(?:v[\d.]+/)?containers/[a-zA-Z0-9_.-]+/kill$")),
    ("GET", re.compile(r"^/(?:v[\d.]+/)?containers/[a-zA-Z0-9_.-]+/logs$")),
    ("GET", re.compile(r"^/(?:v[\d.]+/)?containers/[a-zA-Z0-9_.-]+/json$")),
    ("GET", re.compile(r"^/(?:v[\d.]+/)?containers/json$")),
    ("DELETE", re.compile(r"^/(?:v[\d.]+/)?containers/[a-zA-Z0-9_.-]+$")),
    # The SDK pings on connect; refusing it would break every client before it starts.
    ("GET", re.compile(r"^/(?:v[\d.]+/)?_ping$")),
    ("HEAD", re.compile(r"^/(?:v[\d.]+/)?_ping$")),
    ("GET", re.compile(r"^/(?:v[\d.]+/)?version$")),
)

#: HostConfig keys the sandbox sets, and nothing more. Anything absent is refused by
#: name so a legitimate addition is a deliberate edit rather than a silent pass.
ALLOWED_HOST_CONFIG: frozenset[str] = frozenset(
    {
        "Mounts",
        "Tmpfs",
        "NetworkMode",
        "ReadonlyRootfs",
        "Memory",
        "MemorySwap",
        "CpuQuota",
        "CpuPeriod",
        "PidsLimit",
        "CapDrop",
        "SecurityOpt",
        "AutoRemove",
        "Init",
        "LogConfig",
    }
)

#: Top-level create-body keys the SDK sends. Same allowlist discipline.
ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "Image",
        "Cmd",
        "Entrypoint",
        "Env",
        "WorkingDir",
        "User",
        "Labels",
        "HostConfig",
        "NetworkDisabled",
        "AttachStdout",
        "AttachStderr",
        "AttachStdin",
        "OpenStdin",
        "StdinOnce",
        "Tty",
        "Hostname",
        "Domainname",
        "NetworkingConfig",
    }
)

#: The only security options that may be requested. no-new-privileges is what the
#: sandbox sets; seccomp and apparmor are refused entirely because the only reason to
#: name them here is to weaken them.
ALLOWED_SECURITY_OPT = frozenset({"no-new-privileges", "no-new-privileges:true"})


def _check_mounts(mounts: Any) -> Verdict:
    """Every mount must be a read-only bind. A writable one is a foothold on the host."""
    if not isinstance(mounts, list):
        return deny("HostConfig.Mounts must be a list")
    for mount in mounts:
        if not isinstance(mount, dict):
            return deny("each mount must be an object")
        if mount.get("Type") != "bind":
            return deny(f"mount type {mount.get('Type')!r} is not permitted; only bind is")
        if mount.get("ReadOnly") is not True:
            return deny(
                f"the mount of {mount.get('Source')!r} is not read-only. A writable host "
                "mount lets a container modify the machine analysing it."
            )
    return ALLOW


def _check_host_config(host: Any) -> Verdict:
    if not isinstance(host, dict):
        return deny("HostConfig must be an object")

    unknown = sorted(set(host) - ALLOWED_HOST_CONFIG)
    if unknown:
        # The allowlist failing closed on an unrecognised key is the whole point: this is
        # where Privileged, CapAdd, Devices, PidMode and Sysctls are caught, including
        # ones Docker has not invented yet.
        return deny(
            f"HostConfig keys not permitted: {', '.join(unknown)}. The sandbox sets a "
            "fixed set of options and anything else is refused by default."
        )

    if "NetworkMode" in host and host["NetworkMode"] != "none":
        return deny(
            f"NetworkMode {host['NetworkMode']!r} is not permitted; the analysis "
            "container has no network by design (ADR 0009)."
        )

    if "ReadonlyRootfs" in host and host["ReadonlyRootfs"] is not True:
        return deny("ReadonlyRootfs must be true")

    if "CapDrop" in host and "ALL" not in (host["CapDrop"] or []):
        return deny("CapDrop must include ALL")

    for option in host.get("SecurityOpt") or []:
        if str(option) not in ALLOWED_SECURITY_OPT:
            return deny(
                f"SecurityOpt {option!r} is not permitted. Naming seccomp or apparmor "
                "here can only weaken them."
            )

    if "Mounts" in host:
        verdict = _check_mounts(host["Mounts"])
        if not verdict.allowed:
            return verdict

    # Binds is the legacy spelling of Mounts and is not in the allowlist, so it is
    # already refused above. This assertion documents that rather than re-checking it.
    return ALLOW


def validate(method: str, path: str, body: Any) -> Verdict:
    """Whether this Docker API request may be forwarded to the daemon.

    ``body`` is the decoded JSON for a create request and may be None for anything else.
    """
    method = method.upper()
    route = path.split("?", 1)[0]

    if not any(m == method and pattern.match(route) for m, pattern in ALLOWED_ROUTES):
        return deny(f"{method} {route} is not an endpoint the sandbox uses.")

    if not (method == "POST" and route.endswith("/containers/create")):
        return ALLOW

    if not isinstance(body, dict):
        return deny("a container create request must carry a JSON object body")

    unknown = sorted(set(body) - ALLOWED_TOP_LEVEL)
    if unknown:
        return deny(f"container create keys not permitted: {', '.join(unknown)}")

    if "HostConfig" not in body:
        # Without a HostConfig the daemon applies its own defaults, which include a
        # writable root filesystem and a bridged network. The sandbox always sends one.
        return deny("a container create request must carry a HostConfig")

    return _check_host_config(body["HostConfig"])
