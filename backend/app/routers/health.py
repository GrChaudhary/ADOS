from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "env": settings.env, "event_bus_backend": settings.event_bus_backend}
