"""
AuditTrail — Postgres-backed path (session_factory set). orchestrate/
audit_trail.py. Requires `docker compose up -d postgres` +
`alembic upgrade head` applied to ados_test (conftest.py points
DATABASE_URL there for the whole suite).

Covers what's genuinely new and DB-specific: durability across a fresh
AuditTrail instance (simulating a process restart), the upsert-by-
incident_id replace semantics an AwaitingApproval snapshot then a
terminal append() rely on, persist_snapshot()'s deliberate no-in-memory-
append behavior, and graceful degradation when the Postgres write itself
fails (mirrors the old Cloudant write-through's "never fail the incident
over an audit-log write" convention — see the module docstring).
"""

import pytest
from sqlalchemy import text

from contracts import IncidentRecord, PolicyTier
from db.engine import async_session_factory
from orchestrate.audit_trail import AuditTrail


@pytest.fixture(autouse=True)
async def _clean_incidents_table():
    async with async_session_factory() as session:
        await session.execute(text("TRUNCATE incidents CASCADE"))
        await session.commit()
    yield


def _record(incident_id: str = "INC-PG-1", final_state: str = "Resolved") -> IncidentRecord:
    return IncidentRecord(
        incident_id=incident_id,
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-27T00:00:00Z",
        final_state=final_state,
        confidence=0.95,
        policy_tier=PolicyTier.AUTONOMOUS,
    )


@pytest.mark.asyncio
async def test_append_persists_and_survives_a_fresh_instance():
    """The actual property this migration exists to deliver: durability
    across a process restart. A brand-new AuditTrail has an empty
    in-memory list, but hydrate_from_db() finds the persisted row."""
    writer = AuditTrail(session_factory=async_session_factory)
    await writer.append(_record())

    reader = AuditTrail(session_factory=async_session_factory)
    assert reader.all() == []  # nothing hydrated yet
    loaded = await reader.hydrate_from_db()
    assert loaded == 1
    assert reader.get("INC-PG-1").final_state == "Resolved"


@pytest.mark.asyncio
async def test_append_upserts_by_incident_id_not_duplicates():
    trail = AuditTrail(session_factory=async_session_factory)
    await trail.append(_record(final_state="Resolved"))
    await trail.append(_record(final_state="Failed"))  # same incident_id

    reader = AuditTrail(session_factory=async_session_factory)
    loaded = await reader.hydrate_from_db()
    assert loaded == 1
    assert reader.get("INC-PG-1").final_state == "Failed"


@pytest.mark.asyncio
async def test_persist_snapshot_writes_to_postgres_without_in_memory_append():
    trail = AuditTrail(session_factory=async_session_factory)
    await trail.persist_snapshot(_record(final_state="AwaitingApproval"))

    # Not visible in this process's in-memory list...
    assert trail.all() == []
    # ...but durable, exactly as _snapshot_pending relies on for restart
    # recovery (orchestrator.py's resume_pending_approvals reads
    # audit_trail.all() after hydrate_from_db() runs).
    reader = AuditTrail(session_factory=async_session_factory)
    loaded = await reader.hydrate_from_db()
    assert loaded == 1
    assert reader.get("INC-PG-1").final_state == "AwaitingApproval"


@pytest.mark.asyncio
async def test_snapshot_then_final_append_upserts_to_one_row():
    """Mirrors the real _snapshot_pending -> _finalize sequence: an
    AwaitingApproval snapshot, later replaced in place by the terminal
    record for the same incident_id — never two rows."""
    trail = AuditTrail(session_factory=async_session_factory)
    await trail.persist_snapshot(_record(final_state="AwaitingApproval"))
    await trail.append(_record(final_state="Resolved"))

    reader = AuditTrail(session_factory=async_session_factory)
    loaded = await reader.hydrate_from_db()
    assert loaded == 1
    assert reader.get("INC-PG-1").final_state == "Resolved"


@pytest.mark.asyncio
async def test_append_degrades_gracefully_when_postgres_write_fails():
    def _broken_session_factory():
        raise RuntimeError("Postgres unreachable")

    trail = AuditTrail(session_factory=_broken_session_factory)
    record = _record()
    result = await trail.append(record)

    # In-memory append must still succeed even though the Postgres write failed.
    assert result is record
    assert trail.get("INC-PG-1") is record
    assert trail.all() == [record]
