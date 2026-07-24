from .base import EventBus
from .memory_bus import InMemoryEventBus
from .redis_bus import RedisEventBus

__all__ = ["EventBus", "InMemoryEventBus", "RedisEventBus", "get_event_bus"]


def get_event_bus(backend: str, **kwargs) -> EventBus:
    """Factory — see ../config.py's event_bus_backend setting.
    docs/010-api-contracts.md leaves the bus technology an open question;
    this keeps producers/consumers decoupled from that choice."""
    if backend == "redis":
        return RedisEventBus(**kwargs)
    return InMemoryEventBus()
