"""
SSE live event stream for the Mission Control agent timeline (Phase 2).
Separate router from events.py because browser EventSource can't set an
Authorization header — this accepts the service token via ?token= instead,
same shared-secret trust model as require_service_auth (backend/app/auth.py).
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ..config import settings

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream_events(
    request: Request,
    token: str = Query(...),
    incident_id: Optional[str] = Query(None),
    max_events: Optional[int] = Query(None),
):
    if token != settings.service_auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")

    async def event_generator():
        count = 0
        try:
            yield ": ping\n\n"
            count += 1
            if max_events is not None and count >= max_events:
                return

            stream_iter = request.app.state.event_bus.stream().__aiter__()
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        envelope = await asyncio.wait_for(stream_iter.__anext__(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        break

                    if incident_id is not None and envelope.incident_id != incident_id:
                        continue

                    yield f"data: {envelope.model_dump_json(by_alias=True)}\n\n"
                    count += 1
                    if max_events is not None and count >= max_events:
                        break
            finally:
                # Deregister this connection's subscriber queue from the bus
                # immediately on disconnect/return — without this, InMemoryEventBus
                # keeps publishing to it forever, relying on GC finalization of
                # the abandoned async generator to ever unsubscribe (unreliable).
                await stream_iter.aclose()
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")
