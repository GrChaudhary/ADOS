"""
Event Envelope contract implementation per docs/010-api-contracts.md.
Provides the standard envelope shape for every event emitted on the ADOS event bus.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict

from .trace_context import current_trace_id


class EventEnvelope(BaseModel):
    """
    Standard event envelope for all ADOS cross-layer events.
    """
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        alias="eventId",
        description="Unique identifier for this event instance"
    )
    event_type: str = Field(
        ...,
        alias="eventType",
        description="Type of event (e.g., IncidentDetected, AgentCompleted)"
    )
    correlation_id: str = Field(
        ...,
        alias="correlationId",
        description=(
            "ID grouping every event belonging to the same unit of work — "
            "an incident ID for today's manufacturing pipeline, but generic "
            "so non-manufacturing domains (HR, Finance, ...) aren't forced "
            "to have an 'incident'"
        )
    )
    occurred_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        alias="occurredAt",
        description="ISO-8601 timestamp when the event occurred"
    )
    produced_by: str = Field(
        ...,
        alias="producedBy",
        description="Layer or service component that emitted this event"
    )
    schema_version: str = Field(
        default="2.0.0",
        alias="schemaVersion",
        description="Semantic version of the payload schema"
    )
    trace_id: Optional[str] = Field(
        default_factory=current_trace_id,
        alias="traceId",
        description=(
            "Correlates every event produced while handling one HTTP request. "
            "Populated automatically from contracts/trace_context.py, which "
            "backend/app/observability.py's RequestIdMiddleware sets per "
            "request — so all 7 producers get it without any of them being "
            "changed. None outside a request (background task, script, test), "
            "which is a normal value, not an error."
        )
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        alias="idempotencyKey",
        description=(
            "Lets a consumer recognize a republished/retried event as the "
            "same logical occurrence rather than a new one. Unpopulated "
            "until a producer actually retries a publish — no producer "
            "does that today."
        )
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific payload object"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return canonical dictionary representation with camelCase keys."""
        return self.model_dump(by_alias=True)
