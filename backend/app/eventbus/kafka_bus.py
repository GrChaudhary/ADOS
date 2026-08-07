"""
Kafka-backed event bus. Opt-in via EVENT_BUS_BACKEND=kafka — see
infrastructure/EVENT_BUS_COMPARISON.md for the original "not needed yet"
verdict and its 2026-08-04 reversal.

Design: one internal AIOKafkaConsumer, started once in start() and run as
a background task for the lifetime of the process, is the single reader
of the topic. It fans out each message to two places — a bounded
in-memory ring buffer (recent()'s source) and a set of per-subscriber
asyncio.Queues (stream()'s source) — the exact same two-sink shape
memory_bus.py's InMemoryEventBus already uses, just fed by Kafka instead
of being fed directly by publish(). This keeps recent()/stream() O(1)
against in-memory state rather than re-querying Kafka on every call: Kafka
has no native "give me the last N messages" query the way Redis Streams'
XREVRANGE does, so serving that from a live query every time would mean
re-consuming from an offset on every request.

The internal consumer group_id is unique per KafkaEventBus instance
(uuid4-suffixed), not a fixed name — a fresh process is meant to replay
the topic from the earliest offset into its own fresh in-memory view on
every restart, matching InMemoryEventBus's behavior (history rebuilt from
scratch, not resumed from a shared checkpoint) rather than introducing a
different, durable-cross-restart-position feature nobody asked for here.
"""

import asyncio
import json
import uuid
from typing import AsyncIterator, List, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from contracts import EventEnvelope

from .base import EventBus


class KafkaEventBus(EventBus):
    def __init__(
        self,
        bootstrap_servers: str,
        topic: str = "ados.events",
        max_history: int = 1000,
    ):
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._max_history = max_history
        self._group_id = f"ados-eventbus-internal-{uuid.uuid4()}"

        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._consume_task: Optional[asyncio.Task] = None

        self._history: List[EventEnvelope] = []
        self._subscribers: List[asyncio.Queue] = []

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._producer.start()

        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        self._consume_task = asyncio.create_task(self._consume_loop())

    async def aclose(self) -> None:
        if self._consume_task is not None:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
        if self._consumer is not None:
            await self._consumer.stop()
        if self._producer is not None:
            await self._producer.stop()

    async def _consume_loop(self) -> None:
        async for record in self._consumer:
            envelope = EventEnvelope.model_validate(json.loads(record.value))
            self._history.append(envelope)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            for queue in self._subscribers:
                await queue.put(envelope)

    async def publish(self, envelope: EventEnvelope) -> None:
        await self._producer.send_and_wait(
            self._topic,
            value=json.dumps(envelope.to_dict()).encode("utf-8"),
            key=envelope.correlation_id.encode("utf-8"),
        )

    async def recent(
        self, correlation_id: Optional[str] = None, limit: int = 100
    ) -> List[EventEnvelope]:
        events = self._history
        if correlation_id is not None:
            events = [e for e in events if e.correlation_id == correlation_id]
        return events[-limit:]

    async def stream(self) -> AsyncIterator[EventEnvelope]:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.remove(queue)
