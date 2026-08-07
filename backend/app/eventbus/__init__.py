from .base import EventBus
from .memory_bus import InMemoryEventBus
from .redis_bus import RedisEventBus
from .kafka_bus import KafkaEventBus

__all__ = ["EventBus", "InMemoryEventBus", "RedisEventBus", "KafkaEventBus", "get_event_bus"]


def get_event_bus(backend: str, **kwargs) -> EventBus:
    """Factory — see ../config.py's event_bus_backend setting.
    docs/010-api-contracts.md's "Kafka vs. a managed event bus" question
    is resolved (infrastructure/EVENT_BUS_COMPARISON.md) — kafka is a real
    option now, not just memory/redis."""
    if backend == "kafka":
        return KafkaEventBus(**kwargs)
    if backend == "redis":
        return RedisEventBus(**kwargs)
    return InMemoryEventBus()
