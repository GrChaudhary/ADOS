"""
Tests for Section 5.4 Durable Kafka Async Approval Queue & Event Bus Stream.
"""

import pytest
from contracts import EventEnvelope
from backend.app.eventbus.memory_bus import InMemoryEventBus
from orchestrate.async_approvals import (
    publish_pending_approval_event,
    publish_approval_decision_event,
    GOVERNANCE_APPROVAL_TOPIC,
)


@pytest.mark.asyncio
async def test_publish_pending_approval_event():
    """Verify that publish_pending_approval_event publishes a valid EventEnvelope to the event bus."""
    bus = InMemoryEventBus()

    envelope = await publish_pending_approval_event(
        task_id="task-12345",
        domain="it",
        action_key="revoke_aws_role",
        capability="RevokeAWSRole",
        policy_tier=1,
        estimated_cost_usd=40000.0,
        summary="Revoke AWS IAM admin role",
        bus=bus,
    )

    assert envelope.event_type == "GovernancePendingApproval"
    assert envelope.correlation_id == "task-12345"
    assert envelope.payload["taskId"] == "task-12345"
    assert envelope.payload["actionKey"] == "revoke_aws_role"
    assert envelope.payload["policyTier"] == 1

    recent = await bus.recent(correlation_id="task-12345")
    assert len(recent) == 1
    assert recent[0].event_id == envelope.event_id


@pytest.mark.asyncio
async def test_publish_approval_decision_event():
    """Verify that publish_approval_decision_event publishes a valid EventEnvelope to the event bus."""
    bus = InMemoryEventBus()

    envelope = await publish_approval_decision_event(
        task_id="task-12345",
        decision="approved",
        approved_by="sophia",
        role="executive",
        bus=bus,
    )

    assert envelope.event_type == "GovernanceApprovalDecision"
    assert envelope.correlation_id == "task-12345"
    assert envelope.payload["taskId"] == "task-12345"
    assert envelope.payload["decision"] == "approved"
    assert envelope.payload["approvedBy"] == "sophia"
    assert envelope.payload["role"] == "executive"

    recent = await bus.recent(correlation_id="task-12345")
    assert len(recent) == 1
    assert recent[0].event_id == envelope.event_id
