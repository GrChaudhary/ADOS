"""
In-memory event bus — the Phase 1 default so local dev and tests don't
require Redis running. Not durable across restarts and not shared across
processes; swap to RedisEventBus (EVENT_BUS_BACKEND=redis) once multiple
services need to consume the same stream.
"""

import asyncio
from typing import AsyncIterator, List, Optional

from contracts import EventEnvelope

from .base import EventBus


class InMemoryEventBus(EventBus):
    def __init__(self, max_history: int = 1000):
        self._history: List[EventEnvelope] = []
        self._max_history = max_history
        self._subscribers: List[asyncio.Queue] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        self._history.append(envelope)
        if len(self._history) > self._max_history:
            self._history.pop(0)
        for queue in self._subscribers:
            await queue.put(envelope)

    async def recent(
        self, incident_id: Optional[str] = None, limit: int = 100
    ) -> List[EventEnvelope]:
        events = self._history
        if incident_id is not None:
            events = [e for e in events if e.incident_id == incident_id]
        return events[-limit:]

    async def stream(self) -> AsyncIterator[EventEnvelope]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.remove(queue)
