"""Version 1 API routers.

Health probes are deliberately *not* here: they are infrastructure, not API surface, and
versioning them would break probes on every version bump.
"""

from fastapi import APIRouter

from app.api.v1 import scans

api_router = APIRouter()
api_router.include_router(scans.router)

__all__ = ["api_router"]
