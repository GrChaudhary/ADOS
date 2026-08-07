"""
Minimal event bus surface for local dev/demo and for other services
(agents, orchestrate) to publish/inspect events over HTTP instead of
importing the bus directly. Real intra-process consumers should use
app.state.event_bus.stream() directly rather than polling this.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request

from contracts import EventEnvelope

from ..auth import get_current_user

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(get_current_user)])


@router.post("", response_model=EventEnvelope)
async def publish_event(envelope: EventEnvelope, request: Request):
    await request.app.state.event_bus.publish(envelope)
    return envelope


@router.get("", response_model=list[EventEnvelope])
async def list_recent_events(
    request: Request, correlation_id: Optional[str] = None, limit: int = 100
):
    return await request.app.state.event_bus.recent(correlation_id=correlation_id, limit=limit)
