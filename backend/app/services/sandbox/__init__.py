"""Container isolation for analysing untrusted repositories (constraint C1).

Nothing outside this package may execute target-repository code.
"""

from app.services.sandbox.errors import (
    SandboxConfigurationError,
    SandboxError,
    SandboxImageMissingError,
    SandboxUnavailableError,
)
from app.services.sandbox.result import SandboxOutcome, SandboxResult
from app.services.sandbox.runner import (
    OWNER_LABEL,
    OWNER_LABEL_VALUE,
    RUN_ID_LABEL,
    SCRATCH_PATH,
    WORKSPACE_PATH,
    Sandbox,
)

__all__ = [
    "OWNER_LABEL",
    "OWNER_LABEL_VALUE",
    "RUN_ID_LABEL",
    "SCRATCH_PATH",
    "WORKSPACE_PATH",
    "Sandbox",
    "SandboxConfigurationError",
    "SandboxError",
    "SandboxImageMissingError",
    "SandboxOutcome",
    "SandboxResult",
    "SandboxUnavailableError",
]
