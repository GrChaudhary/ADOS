"""
Event bus abstraction — docs/010-api-contracts.md's event envelope is the
payload; this defines how it moves between producers and consumers without
callers caring whether the backend is in-memory or Redis.
"""

import abc
from typing import AsyncIterator, List, Optional

from contracts import EventEnvelope


class EventBus(abc.ABC):
    @abc.abstractmethod
    async def publish(self, envelope: EventEnvelope) -> None:
        """Publish an event. Producers set incident_id on every event from
        Detected onward per docs/010-api-contracts.md, so incidents stay
        replayable from the log alone."""

    @abc.abstractmethod
    async def recent(
        self, incident_id: Optional[str] = None, limit: int = 100
    ) -> List[EventEnvelope]:
        """Return the most recent published events, optionally filtered by
        incident. Intended for debugging/demo and simple polling
        consumers, not a substitute for stream()."""

    @abc.abstractmethod
    async def stream(self) -> AsyncIterator[EventEnvelope]:
        """Yield newly published events as they arrive."""
