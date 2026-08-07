"""
AuditTrail — pure in-memory path (no session_factory). orchestrate/
audit_trail.py. See tests/test_audit_trail_postgres.py for the
Postgres-backed path.
"""

import pytest

from contracts import IncidentRecord, PolicyTier
from orchestrate.audit_trail import AuditTrail


def _record(incident_id: str = "INC-TEST-1") -> IncidentRecord:
    return IncidentRecord(
        incident_id=incident_id,
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-27T00:00:00Z",
        final_state="Resolved",
        confidence=0.95,
        policy_tier=PolicyTier.AUTONOMOUS,
    )


@pytest.mark.asyncio
async def test_append_adds_to_in_memory_list():
    trail = AuditTrail()
    record = _record()
    result = await trail.append(record)

    assert result is record
    assert trail.get("INC-TEST-1") is record
    assert trail.all() == [record]


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_incident():
    trail = AuditTrail()
    assert trail.get("does-not-exist") is None


@pytest.mark.asyncio
async def test_get_returns_the_most_recently_appended_match():
    trail = AuditTrail()
    first = _record()
    second = _record()  # same incident_id, later state
    await trail.append(first)
    await trail.append(second)

    assert trail.get("INC-TEST-1") is second


def test_recent_respects_limit():
    seed = [_record(f"INC-{i}") for i in range(5)]
    trail = AuditTrail(seed_records=seed)
    assert trail.recent(limit=2) == seed[-2:]


@pytest.mark.asyncio
async def test_persist_snapshot_is_a_no_op_without_a_session_factory():
    trail = AuditTrail()
    await trail.persist_snapshot(_record())
    # No session_factory configured — nothing to append to in-memory
    # either, since persist_snapshot() never touches _records.
    assert trail.all() == []


@pytest.mark.asyncio
async def test_hydrate_from_db_is_a_no_op_without_a_session_factory():
    trail = AuditTrail()
    loaded = await trail.hydrate_from_db()
    assert loaded == 0
    assert trail.all() == []


def test_default_construction_has_no_side_effects():
    trail = AuditTrail()
    assert trail.all() == []
