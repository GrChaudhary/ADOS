"""
Event Envelope contract implementation per docs/010-api-contracts.md.
Provides the standard envelope shape for every event emitted on the ADOS event bus.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict


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
    incident_id: str = Field(
        ...,
        alias="incidentId",
        description="ID of the incident this event belongs to"
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
        default="1.0.0",
        alias="schemaVersion",
        description="Semantic version of the payload schema"
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific payload object"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return canonical dictionary representation with camelCase keys."""
        return self.model_dump(by_alias=True)
