"""Analysers.

Every analyser here runs its tool **inside the sandbox** (C1, ADR 0009). None of them may
grow a host fallback: an analyser that ran on the host would be executing a target's
tooling against this machine, which is the single thing the container exists to prevent.

Each adapter maps its tool's native vocabulary onto this project's own -- normalised
severities, nullable metrics -- at the adapter boundary, so no tool's idiom leaks past it.
"""

from __future__ import annotations
