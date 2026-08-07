"""
Durable Kafka Async Approval Queue & Event Bus Stream — orchestration-platform-vision.md §5.4.

Publishes pending approval requests and human decisions onto the `governance.pending_approval` Kafka topic
wrapped in EventEnvelope v2 (contracts/event_envelope.py).

Provides a durable, real-time message stream for async audit logging, external webhook triggers
(e.g., Slack/ServiceNow notifications), and event-driven resumes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Optional

from contracts import EventEnvelope, PendingApprovalPayload, ApprovalDecisionPayload
from backend.app.eventbus.base import EventBus
from backend.app.eventbus.memory_bus import InMemoryEventBus

GOVERNANCE_APPROVAL_TOPIC = "governance.pending_approval"

_default_in_memory_bus = InMemoryEventBus()


async def publish_pending_approval_event(
    task_id: str,
    domain: str,
    action_key: str,
    capability: str,
    policy_tier: int,
    estimated_cost_usd: float,
    summary: str,
    bus: Optional[EventBus] = None,
) -> EventEnvelope:
    """Publishes a PendingApproval payload wrapped in an EventEnvelope to the event bus."""
    event_bus = bus if bus is not None else _default_in_memory_bus
    now_iso = datetime.now(timezone.utc).isoformat()

    payload = PendingApprovalPayload(
        task_id=task_id,
        domain=domain,
        action_key=action_key,
        capability=capability,
        policy_tier=policy_tier,
        estimated_cost_usd=estimated_cost_usd,
        summary=summary,
        timestamp=now_iso,
    )

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type="GovernancePendingApproval",
        produced_by="ados-governance-engine",
        correlation_id=task_id,
        occurred_at=now_iso,
        payload=payload.model_dump(by_alias=True),
    )

    await event_bus.publish(envelope)
    return envelope


async def publish_approval_decision_event(
    task_id: str,
    decision: str,
    approved_by: Optional[str] = None,
    role: Optional[str] = None,
    bus: Optional[EventBus] = None,
) -> EventEnvelope:
    """Publishes an ApprovalDecision payload wrapped in an EventEnvelope to the event bus."""
    event_bus = bus if bus is not None else _default_in_memory_bus
    now_iso = datetime.now(timezone.utc).isoformat()

    payload = ApprovalDecisionPayload(
        task_id=task_id,
        decision=decision,
        approved_by=approved_by,
        role=role,
        timestamp=now_iso,
    )

    envelope = EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type="GovernanceApprovalDecision",
        produced_by="ados-governance-engine",
        correlation_id=task_id,
        occurred_at=now_iso,
        payload=payload.model_dump(by_alias=True),
    )

    await event_bus.publish(envelope)
    return envelope
