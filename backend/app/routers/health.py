from fastapi import APIRouter

from orchestrate.runtime.build_identity import CURRENT_BUILD_REVISION

from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    # `build` is this process's own identity, frozen at import time (see
    # orchestrate/runtime/build_identity.py) — never anything a caller can
    # supply, and never recomputed per-request, since the point is to report
    # what code this process actually loaded, not what the repo currently
    # holds. No secrets: a git commit hash and a dirty flag.
    return {
        "status": "ok",
        "env": settings.env,
        "event_bus_backend": settings.event_bus_backend,
        "build": CURRENT_BUILD_REVISION.to_dict(),
    }
