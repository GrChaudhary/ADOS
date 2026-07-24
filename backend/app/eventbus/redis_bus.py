"""
Redis Streams-backed event bus. Opt-in via EVENT_BUS_BACKEND=redis — the
MVP default is the in-memory bus (memory_bus.py); this is here for anyone
running multiple backend processes or wanting durability across restarts.
Kafka vs. a managed bus for production is still open — docs/010-api-contracts.md.
"""

import json
from typing import AsyncIterator, List, Optional

import redis.asyncio as redis

from contracts import EventEnvelope

from .base import EventBus


class RedisEventBus(EventBus):
    def __init__(self, url: str, stream: str = "ados:events"):
        self._client = redis.from_url(url, decode_responses=True)
        self._stream = stream

    async def publish(self, envelope: EventEnvelope) -> None:
        await self._client.xadd(
            self._stream, {"data": json.dumps(envelope.to_dict())}
        )

    async def recent(
        self, incident_id: Optional[str] = None, limit: int = 100
    ) -> List[EventEnvelope]:
        # XREVRANGE returns newest-first; fetch a bit more than `limit` to
        # allow for incident_id filtering, then re-order oldest-first to
        # match InMemoryEventBus.recent()'s contract.
        raw = await self._client.xrevrange(self._stream, count=limit * 5)
        events = [EventEnvelope.model_validate(json.loads(v["data"])) for _, v in raw]
        if incident_id is not None:
            events = [e for e in events if e.incident_id == incident_id]
        return list(reversed(events[:limit]))

    async def stream(self) -> AsyncIterator[EventEnvelope]:
        last_id = "$"  # only new entries from subscription time onward
        while True:
            response = await self._client.xread(
                {self._stream: last_id}, block=5000, count=10
            )
            for _stream_name, entries in response:
                for entry_id, fields in entries:
                    last_id = entry_id
                    yield EventEnvelope.model_validate(json.loads(fields["data"]))
