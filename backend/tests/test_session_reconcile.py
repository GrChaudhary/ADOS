"""
Reconciliation for sessions abandoned by an ADOS process failure
(orchestrate/runtime/session_reconcile.py).

The scenario under test is deliberately NOT reproducible by raising an
exception inside a running test process: P6-D's `finally`-block fix already
covers that. What is under test here is the case P6-D *cannot* cover — the
process itself dying, exactly as it did for the three real Aug 9 sessions
(see docs/prime-agent-integration/14-known-limitations.md) — modelled by
inserting a row directly, the same way that scenario actually looks in
Postgres: `state` stuck non-terminal, nobody left to run a `finally`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from orchestrate.runtime import orphan_sweep as sweep
from orchestrate.runtime.session_reconcile import reconcile_abandoned_sessions


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


async def _make_abandoned_session(
    *, state: str = "running", token_expires_at=None, container_name=None, workspace_path=None,
) -> uuid.UUID:
    async with async_session_factory() as db:
        mission = MissionRow(
            title="ados-died-mid-mission test", objective="test", domain="it",
            allowed_capabilities=[], status="running", created_by="test",
        )
        db.add(mission)
        await db.flush()
        row = RuntimeSessionRow(
            mission_id=mission.mission_id,
            state=state,
            token_expires_at=token_expires_at,
            container_name=container_name,
            workspace_path=workspace_path,
        )
        db.add(row)
        await db.commit()
        return row.session_id


async def _fetch(session_id: uuid.UUID) -> RuntimeSessionRow:
    async with async_session_factory() as db:
        return await db.get(RuntimeSessionRow, session_id)


async def test_a_session_with_an_expired_token_and_stuck_non_terminal_is_reconciled():
    expired = datetime.now(timezone.utc) - timedelta(hours=2)
    session_id = await _make_abandoned_session(state="running", token_expires_at=expired)

    reconciled = await reconcile_abandoned_sessions(async_session_factory)
    assert any(r.session_id == session_id for r in reconciled)

    row = await _fetch(session_id)
    assert row.state == "failed"
    assert "orphaned" in row.failure_reason.lower()


async def test_a_session_whose_token_has_not_yet_expired_is_left_alone():
    not_yet = datetime.now(timezone.utc) + timedelta(hours=1)
    session_id = await _make_abandoned_session(state="running", token_expires_at=not_yet)

    reconciled = await reconcile_abandoned_sessions(async_session_factory)
    assert not any(r.session_id == session_id for r in reconciled)

    row = await _fetch(session_id)
    assert row.state == "running"


async def test_a_session_with_no_expiry_at_all_is_left_alone():
    """The pre-P6-D fossil shape: NULL token_expires_at. There is no
    deterministic proof the credential is dead, so this module refuses to
    guess — exactly the three real Aug 9 rows, still NULL today."""
    session_id = await _make_abandoned_session(state="running", token_expires_at=None)

    reconciled = await reconcile_abandoned_sessions(async_session_factory)
    assert not any(r.session_id == session_id for r in reconciled)

    row = await _fetch(session_id)
    assert row.state == "running"


async def test_an_already_terminal_session_is_never_touched_even_with_an_expired_token():
    expired = datetime.now(timezone.utc) - timedelta(hours=2)
    session_id = await _make_abandoned_session(state="completed", token_expires_at=expired)

    reconciled = await reconcile_abandoned_sessions(async_session_factory)
    assert not any(r.session_id == session_id for r in reconciled)

    row = await _fetch(session_id)
    assert row.state == "completed"  # unchanged — reconciliation must not touch a real completion


async def test_waiting_for_approval_with_an_expired_token_is_reconciled_not_left_hanging():
    expired = datetime.now(timezone.utc) - timedelta(hours=2)
    session_id = await _make_abandoned_session(state="waiting_for_approval", token_expires_at=expired)

    reconciled = await reconcile_abandoned_sessions(async_session_factory)
    assert any(r.session_id == session_id for r in reconciled)


async def test_reconciliation_is_bounded_by_limit():
    for _ in range(3):
        await _make_abandoned_session(
            state="running", token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    reconciled = await reconcile_abandoned_sessions(async_session_factory, limit=1)
    assert len(reconciled) == 1


async def test_reconciliation_is_idempotent():
    expired = datetime.now(timezone.utc) - timedelta(hours=2)
    session_id = await _make_abandoned_session(state="running", token_expires_at=expired)

    first = await reconcile_abandoned_sessions(async_session_factory)
    assert any(r.session_id == session_id for r in first)

    second = await reconcile_abandoned_sessions(async_session_factory)
    assert not any(r.session_id == session_id for r in second)  # already terminal now


async def test_two_concurrent_reconciliations_never_double_process_the_same_row():
    import asyncio

    expired = datetime.now(timezone.utc) - timedelta(hours=1)
    for _ in range(5):
        await _make_abandoned_session(state="running", token_expires_at=expired)

    results = await asyncio.gather(
        reconcile_abandoned_sessions(async_session_factory),
        reconcile_abandoned_sessions(async_session_factory),
    )
    a, b = results
    ids_a = {r.session_id for r in a}
    ids_b = {r.session_id for r in b}
    assert ids_a.isdisjoint(ids_b)
    assert len(ids_a) + len(ids_b) == 5


async def test_a_reconciled_session_becomes_sweepable_by_the_existing_unmodified_sweeper(monkeypatch):
    """The point of the whole module: reconciliation does not touch Docker or
    the filesystem itself. It only has to make the row visible to
    orphan_sweep.py, unchanged, for the orphan candidates (container/relay/
    networks/workspace) to actually get cleaned up on the next sweep."""
    async def fake_label(kind, name):
        return None  # nothing real exists; proves the WIRING, not Docker itself

    monkeypatch.setattr(sweep, "_docker_label", fake_label)

    expired = datetime.now(timezone.utc) - timedelta(hours=2)
    session_id = await _make_abandoned_session(
        state="running", token_expires_at=expired, container_name="ados-prime-reconciled1",
    )

    reconciled = await reconcile_abandoned_sessions(async_session_factory)
    assert any(r.session_id == session_id for r in reconciled)

    report = await sweep.sweep_once(async_session_factory)
    mine = [o for o in report.outcomes if o.item.session_id == session_id]
    assert len(mine) == 4  # container + relay + 2 networks (no workspace_path here)
    assert all(o.status == "absent" for o in mine)
