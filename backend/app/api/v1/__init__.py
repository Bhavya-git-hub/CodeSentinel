"""Version 1 API routers.

Empty until phase 3, which adds the scans, results, graph and reports routers.
Health probes are deliberately *not* here: they are infrastructure, not API surface,
and versioning them would break probes on every version bump.
"""

from fastapi import APIRouter

api_router = APIRouter()

__all__ = ["api_router"]
