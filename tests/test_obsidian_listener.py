"""
Tests for event-driven ObsidianProjectionListener.

These deliberately drive the listener with event types produced by real
publishers (orchestrate/async_approvals.py) rather than hand-written
strings. An earlier version of this test asserted against
event_type="moa.task.started", which no producer in this codebase ever
emits — so it passed while the listener projected nothing in production.
"""

import asyncio
import pytest

from backend.app.eventbus.memory_bus import InMemoryEventBus
from contracts import EventEnvelope
from orchestrate.async_approvals import (
    publish_approval_decision_event,
    publish_pending_approval_event,
)
from orchestrate.obsidian.listener import ObsidianProjectionListener
from orchestrate.obsidian.writer import ObsidianVaultWriter


def _listener(tmp_path) -> ObsidianProjectionListener:
    return ObsidianProjectionListener(writer=ObsidianVaultWriter(target_dir=tmp_path))


async def _drain(listener: ObsidianProjectionListener) -> None:
    """Waits for the background worker to finish the queued events."""
    await asyncio.wait_for(listener._queue.join(), timeout=5)


async def _wait_for_projections(listener: ObsidianProjectionListener, count: int) -> None:
    """Waits for `count` notes to actually land.

    Events published to a bus take two hops (bus stream -> listener queue ->
    writer), so joining the listener queue alone can return before the
    forwarding task has even enqueued anything.
    """
    for _ in range(500):
        if listener.get_stats()["projected_count"] >= count:
            await _drain(listener)
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"expected {count} projections, got {listener.get_stats()['projected_count']}"
    )


@pytest.mark.asyncio
async def test_pending_approval_event_projects_a_live_task_note(tmp_path):
    listener = _listener(tmp_path)
    await listener.start()
    try:
        listener.on_event(EventEnvelope(
            event_type="GovernancePendingApproval",
            produced_by="ados-governance-engine",
            correlation_id="task-abcdef12-9999",
            payload={
                "taskId": "task-abcdef12-9999",
                "domain": "hr",
                "actionKey": "stop_payroll",
                "capability": "StopPayroll",
                "policyTier": 2,
                "estimatedCostUsd": 12500.0,
                "summary": "Stop payroll for Marcus Vance",
                "timestamp": "2026-08-06T00:00:00+00:00",
            },
        ))
        await _drain(listener)

        note = tmp_path / "04_Live_Tasks" / "Task-task-abc.md"
        assert note.exists()
        content = note.read_text(encoding="utf-8")
        assert "Stop payroll for Marcus Vance" in content
        assert "[[StopPayroll]]" in content
        assert "PENDING_APPROVAL" in content
        # Pod wikilink has to match the reconciler's actual pod note title.
        assert "[[HR Domain Pod]]" in content
        assert "[[Hr Domain Pod]]" not in content
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_approval_decision_event_projects_an_audit_ledger_note(tmp_path):
    listener = _listener(tmp_path)
    await listener.start()
    try:
        listener.on_event(EventEnvelope(
            event_type="GovernanceApprovalDecision",
            produced_by="ados-governance-engine",
            correlation_id="task-abcdef12-9999",
            payload={
                "taskId": "task-abcdef12-9999",
                "decision": "approved",
                "approvedBy": "sophia",
                "role": "executive",
                "timestamp": "2026-08-06T00:00:00+00:00",
            },
        ))
        await _drain(listener)

        ledger = list((tmp_path / "05_Audit_Ledger").glob("Decision-*.md"))
        assert len(ledger) == 1
        content = ledger[0].read_text(encoding="utf-8")
        assert "APPROVED" in content
        assert "[[sophia (executive)]]" in content
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_decision_note_inherits_capability_and_cost_from_the_pending_event(tmp_path):
    """The decision payload carries no capability/cost — the listener has to
    correlate it with the pending event that preceded it, or the audit record
    is missing exactly the facts an auditor needs."""
    listener = _listener(tmp_path)
    await listener.start()
    try:
        listener.on_event(EventEnvelope(
            event_type="GovernancePendingApproval",
            produced_by="ados-governance-engine",
            correlation_id="task-cafe1234-1",
            payload={
                "taskId": "task-cafe1234-1", "domain": "finance",
                "actionKey": "process_wire_transfer", "capability": "ProcessWireTransfer",
                "policyTier": 2, "estimatedCostUsd": 4200.5,
                "summary": "Wire $4,200.50 to vendor", "timestamp": "2026-08-06T00:00:00+00:00",
            },
        ))
        listener.on_event(EventEnvelope(
            event_type="GovernanceApprovalDecision",
            produced_by="ados-governance-engine",
            correlation_id="task-cafe1234-1",
            payload={
                "taskId": "task-cafe1234-1", "decision": "rejected",
                "approvedBy": "marcus", "role": "manager",
                "timestamp": "2026-08-06T00:01:00+00:00",
            },
        ))
        await _drain(listener)

        content = list((tmp_path / "05_Audit_Ledger").glob("Decision-*.md"))[0].read_text(encoding="utf-8")
        assert "[[ProcessWireTransfer]]" in content
        assert "$4,200.50" in content
        assert "Wire $4,200.50 to vendor" in content
        assert "REJECTED" in content
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_replaying_the_same_decision_event_rewrites_one_note_not_many(tmp_path):
    """Decision ids derive from the event id, not the wall clock, so a
    restart/replay is idempotent instead of littering the ledger."""
    listener = _listener(tmp_path)
    await listener.start()
    try:
        envelope = EventEnvelope(
            event_type="GovernanceApprovalDecision",
            produced_by="ados-governance-engine",
            correlation_id="task-deadbeef-7",
            payload={
                "taskId": "task-deadbeef-7", "decision": "approved",
                "approvedBy": "admin", "role": "admin",
                "timestamp": "2026-08-06T00:00:00+00:00",
            },
        )
        listener.on_event(envelope)
        await _drain(listener)
        listener.on_event(envelope)
        await _drain(listener)

        assert len(list((tmp_path / "05_Audit_Ledger").glob("Decision-*.md"))) == 1
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_unrelated_event_types_are_ignored_without_erroring(tmp_path):
    listener = _listener(tmp_path)
    await listener.start()
    try:
        listener.on_event(EventEnvelope(
            event_type="CapabilityInvocationStarted",
            produced_by="orchestrate/decision-orchestrator",
            correlation_id="INC-1",
            payload={"capability": "RestartLine", "targetLineId": "LINE-1"},
        ))
        await _drain(listener)

        assert listener.get_stats()["projected_count"] == 0
        assert not list(tmp_path.rglob("*.md"))
    finally:
        await listener.stop()


@pytest.mark.asyncio
async def test_real_publisher_reaches_the_listener_over_a_shared_event_bus(tmp_path):
    """End-to-end over the real publisher and a real bus — the wiring that
    was broken: moa.py published to async_approvals' private module-level
    bus, which the listener never streams from."""
    bus = InMemoryEventBus()
    listener = _listener(tmp_path)
    await listener.start()
    bus_task = asyncio.create_task(listener.listen_to_bus(bus))

    # stream() only registers its queue once the async generator is first
    # iterated, so publishing immediately would drop the event on the floor.
    for _ in range(200):
        if bus._subscribers:
            break
        await asyncio.sleep(0.01)
    assert bus._subscribers, "listener never subscribed to the bus"

    try:
        await publish_pending_approval_event(
            task_id="task-11112222-3", domain="it", action_key="revoke_aws_role",
            capability="RevokeAWSRole", policy_tier=1, estimated_cost_usd=0.0,
            summary="Revoke AWS role for departing contractor", bus=bus,
        )
        await publish_approval_decision_event(
            task_id="task-11112222-3", decision="approved",
            approved_by="emma", role="manager", bus=bus,
        )
        await _wait_for_projections(listener, 2)

        assert (tmp_path / "04_Live_Tasks" / "Task-task-111.md").exists()
        ledger = list((tmp_path / "05_Audit_Ledger").glob("Decision-*.md"))
        assert len(ledger) == 1
        assert "[[RevokeAWSRole]]" in ledger[0].read_text(encoding="utf-8")
    finally:
        bus_task.cancel()
        await listener.stop()
