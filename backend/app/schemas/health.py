"""Health and readiness response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DependencyState = Literal["ok", "unavailable"]


class DependencyHealth(BaseModel):
    """State of one external dependency."""

    status: DependencyState
    #: Populated only when the dependency is unavailable. The reason is surfaced rather
    #: than reduced to a bare boolean, so an operator can act on it.
    error: str | None = None


class LivenessResponse(BaseModel):
    """Liveness: the process is running. Checks nothing external."""

    status: Literal["ok"] = "ok"
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    """Readiness: every dependency needed to serve traffic is reachable."""

    status: Literal["ready", "not_ready"]
    dependencies: dict[str, DependencyHealth] = Field(default_factory=dict)
