"""
Live tests against a real Kafka broker — not mocked, matching this
project's convention (Postgres tests are also live-only, no mock/fake
substitute). Requires:

    docker compose up -d kafka

RedisEventBus has zero equivalent coverage today (a real gap, noted in
infrastructure/EVENT_BUS_COMPARISON.md but not fixed there) — don't repeat
that omission for the backend actually being adopted.
"""

import asyncio
import uuid

import pytest

from backend.app.eventbus.kafka_bus import KafkaEventBus
from contracts import EventEnvelope


@pytest.fixture
async def bus():
    # Unique topic per test run so tests never see another test's (or a
    # prior run's) leftover messages on a shared local broker.
    topic = f"ados.events.test.{uuid.uuid4()}"
    instance = KafkaEventBus(bootstrap_servers="localhost:29092", topic=topic)
    await instance.start()
    try:
        yield instance
    finally:
        await instance.aclose()


def _envelope(correlation_id: str, event_type: str = "AgentCompleted") -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        correlation_id=correlation_id,
        produced_by="tests/test_kafka_bus.py",
        payload={"note": "live kafka test"},
    )


async def test_publish_then_recent_round_trips(bus):
    envelope = _envelope("INC-KAFKA-TEST-1")
    await bus.publish(envelope)

    # The background consumer task races the publish; give it a moment to
    # land in the in-memory history buffer rather than asserting instantly.
    for _ in range(50):
        recent = await bus.recent(correlation_id="INC-KAFKA-TEST-1")
        if recent:
            break
        await asyncio.sleep(0.1)

    assert len(recent) == 1
    assert recent[0].event_id == envelope.event_id
    assert recent[0].correlation_id == "INC-KAFKA-TEST-1"
    assert recent[0].payload == {"note": "live kafka test"}


async def test_recent_filters_by_correlation_id(bus):
    await bus.publish(_envelope("INC-KAFKA-A"))
    await bus.publish(_envelope("INC-KAFKA-B"))

    for _ in range(50):
        events = await bus.recent(limit=10)
        if len(events) >= 2:
            break
        await asyncio.sleep(0.1)

    assert {e.correlation_id for e in events} == {"INC-KAFKA-A", "INC-KAFKA-B"}
    only_a = await bus.recent(correlation_id="INC-KAFKA-A")
    assert all(e.correlation_id == "INC-KAFKA-A" for e in only_a)


async def test_stream_yields_published_events_live(bus):
    stream_iter = bus.stream().__aiter__()

    envelope = _envelope("INC-KAFKA-STREAM-1")
    await bus.publish(envelope)

    received = await asyncio.wait_for(stream_iter.__anext__(), timeout=10)
    assert received.event_id == envelope.event_id
    assert received.correlation_id == "INC-KAFKA-STREAM-1"
    await stream_iter.aclose()


async def test_two_stream_subscribers_both_receive_the_same_event(bus):
    stream_a = bus.stream().__aiter__()
    stream_b = bus.stream().__aiter__()

    # stream() is a lazy async generator — its subscriber queue is only
    # registered in bus._subscribers once __anext__() actually starts
    # running, not when __aiter__() is called. Schedule both __anext__()
    # calls as tasks (so both generators start and register their queues
    # on the next event-loop tick) *before* publishing — publishing first
    # would race whichever subscriber hadn't started iterating yet and
    # silently drop the event for it, same lazy-start behavior
    # memory_bus.py's InMemoryEventBus.stream() has (real SSE callers in
    # events_stream.py avoid this by entering their consume loop
    # immediately after __aiter__(), before anything of interest publishes).
    task_a = asyncio.create_task(stream_a.__anext__())
    task_b = asyncio.create_task(stream_b.__anext__())
    await asyncio.sleep(0.1)

    envelope = _envelope("INC-KAFKA-FANOUT-1")
    await bus.publish(envelope)

    received_a = await asyncio.wait_for(task_a, timeout=10)
    received_b = await asyncio.wait_for(task_b, timeout=10)
    assert received_a.event_id == received_b.event_id == envelope.event_id
    await stream_a.aclose()
    await stream_b.aclose()
