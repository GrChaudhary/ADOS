"""
SSE live event stream for the Mission Control agent timeline (Phase 2).
Separate router from events.py because browser EventSource can't set an
Authorization header — this accepts the session JWT via ?token= instead,
verified the same way backend/app/rbac.py's get_current_user() would
(it also accepts a ?token= query param for exactly this reason), just
called directly here since Query(...) already extracts the string and a
second HTTPBearer/Request-based Depends would be redundant.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..rbac import decode_access_token

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def stream_events(
    request: Request,
    token: str = Query(...),
    correlation_id: Optional[str] = Query(None),
    max_events: Optional[int] = Query(None),
):
    # Raises 401 itself (invalid/expired) - same as get_current_user().
    decode_access_token(token)

    async def event_generator():
        count = 0
        try:
            yield ": ping\n\n"
            count += 1
            if max_events is not None and count >= max_events:
                return

            stream_iter = request.app.state.event_bus.stream().__aiter__()

            # Pump the bus's generator into a local queue from a background
            # task, and poll *that* queue with a timeout instead of the bus
            # generator directly. asyncio.Queue.get() is safe to cancel — a
            # timed-out wait_for() just leaves it unconsumed. The bus
            # generator's own get() (inside InMemoryEventBus.stream()) is
            # NOT safe to cancel this way: it has a try/finally that
            # deregisters the subscriber, so cancelling it on every 0.5s
            # timeout (the common case when traffic is quiet) permanently
            # kills and unsubscribes the generator after the first tick —
            # every subsequent __anext__() then raises StopAsyncIteration
            # immediately, which looked like "stream ends right after the
            # ping." Isolating the timeout to the local queue keeps the bus
            # generator's own await from ever being cancelled during normal
            # operation.
            local_queue: asyncio.Queue = asyncio.Queue()

            async def _pump():
                async for envelope in stream_iter:
                    await local_queue.put(envelope)

            pump_task = asyncio.create_task(_pump())
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        envelope = await asyncio.wait_for(local_queue.get(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue

                    if correlation_id is not None and envelope.correlation_id != correlation_id:
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
                pump_task.cancel()
                try:
                    await pump_task
                except asyncio.CancelledError:
                    pass
                await stream_iter.aclose()
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")
