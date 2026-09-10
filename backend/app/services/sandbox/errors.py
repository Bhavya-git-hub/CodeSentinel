"""Sandbox failures.

These are distinct from a command failing *inside* the sandbox. A non-zero exit code is
an ordinary result; these exceptions mean the isolation itself could not be established,
which is never something to degrade past (constraint C1).
"""

from __future__ import annotations


class SandboxError(Exception):
    """Base class for failures to run something under isolation."""


class SandboxUnavailableError(SandboxError):
    """The Docker daemon could not be reached.

    Analysis cannot fall back to running on the host: that would violate C1. A scan whose
    sandbox is unavailable fails, and says so.
    """


class SandboxImageMissingError(SandboxError):
    """The analysis image is not present and cannot be pulled.

    The container has no network, so the image must exist on the host before a run. This
    is reported rather than worked around, because silently substituting a different
    image would change what tool versions produced a result (constraint C5).
    """


class SandboxConfigurationError(SandboxError):
    """The requested isolation could not be configured.

    Raised when a source path does not exist or is not a directory. Refusing here is the
    point: a bind mount of a missing path would otherwise be created by the daemon as an
    empty directory owned by root, and the analysis would silently run against nothing.
    """
