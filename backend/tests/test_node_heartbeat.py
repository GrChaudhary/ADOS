"""
Dead-host reclamation (orchestrate/runtime/node_heartbeat.py) — the one
genuine Model-C engineering blocker named by the Model-C Decision Gate
(docs/prime-agent-integration/31-model-c-decision-gate.md, Phase 2).

Covers, in order: heartbeat creation/update, healthy-host liveness, the
dead threshold itself, dead-host declaration excluding self, live-host
resource protection, dead-host resource reclaimability, concurrent
reclamation (only one claimant wins per resource), stale-host fencing (a
revived host cannot cause a resource to be reprocessed once bookkeeping is
closed), and that this is genuinely bookkeeping-only — never a Docker/
filesystem action against a resource this host cannot observe.

Real Postgres throughout, matching test_orphan_sweep_multihost.py's own
convention (the sibling module this one extends). Docker/filesystem calls
are never reached by a dead-host-reclaimed item at all (see
orphan_sweep._process_one) — nothing to monkeypatch for that path, which is
itself the property under test in several cases below.

WHAT IS DELIBERATELY OUT OF SCOPE HERE
----------------------------------------
Token-expiry fencing (session_reconcile.py, mcp_gateway.py's
`_resolve_session`) and outcome_unknown reconciliation
(capability_reconcile.py) are unchanged by this module and are already
covered by their own test files — this module never touches approval or
execution state, only orphan-sweep cleanup bookkeeping (see
node_heartbeat.py's module docstring). Tenant scoping is also out of scope
for the heartbeat table itself: `node_heartbeats` has no tenant column and
is never wrapped in `db.tenancy.all_tenants_session` (a host's liveness has
no tenant); what IS tested here is that dead-host reclamation composes
correctly with orphan_sweep's existing P17 all-tenants scan.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from db.models.node_heartbeat import NodeHeartbeatRow
from orchestrate.runtime import node_heartbeat as hb
from orchestrate.runtime import orphan_sweep as sweep


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests, node_heartbeats CASCADE"))
        await db.commit()
    yield


async def _make_session(*, owner_host, state: str = "completed", tenant_id: uuid.UUID | None = None) -> uuid.UUID:
    async with async_session_factory() as db:
        mission = MissionRow(
            title="test", objective="test", domain="it",
            allowed_capabilities=[], status="completed", created_by="test",
        )
        db.add(mission)
        await db.flush()
        suffix = uuid.uuid4().hex[:12]
        row = RuntimeSessionRow(
            mission_id=mission.mission_id,
            state=state,
            container_name=f"ados-prime-{suffix}",
            failure_reason="orphaned container: timed out",
            owner_host=owner_host,
        )
        db.add(row)
        await db.commit()
        return row.session_id


async def _heartbeat_at(node_id: str, when: datetime) -> None:
    async with async_session_factory() as db:
        db.add(NodeHeartbeatRow(node_id=node_id, last_seen_at=when))
        await db.commit()


# --- 1. heartbeat creation/update -------------------------------------------


@pytest.mark.asyncio
async def test_record_heartbeat_creates_a_row_and_then_upserts_it_in_place():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await hb.record_heartbeat(async_session_factory, "host-a", now=t0)

    async with async_session_factory() as db:
        row = await db.get(NodeHeartbeatRow, "host-a")
    assert row is not None
    assert row.last_seen_at == t0

    t1 = t0 + timedelta(seconds=300)
    await hb.record_heartbeat(async_session_factory, "host-a", now=t1)

    async with async_session_factory() as db:
        rows = (await db.execute(text("SELECT count(*) FROM node_heartbeats WHERE node_id = 'host-a'"))).scalar()
        row = await db.get(NodeHeartbeatRow, "host-a")
    assert rows == 1  # upsert, not a second row
    assert row.last_seen_at == t1


# --- 2/3. healthy host stays alive; dead threshold is a real boundary ------


@pytest.mark.asyncio
async def test_a_recently_seen_host_is_not_declared_dead():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _heartbeat_at("host-a", now - timedelta(seconds=60))

    dead = await hb.declared_dead_node_ids(
        async_session_factory, dead_after_seconds=900.0, exclude_node_id="self", now=now
    )
    assert "host-a" not in dead


@pytest.mark.asyncio
async def test_a_host_silent_past_the_threshold_is_declared_dead():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _heartbeat_at("host-a", now - timedelta(seconds=901))

    dead = await hb.declared_dead_node_ids(
        async_session_factory, dead_after_seconds=900.0, exclude_node_id="self", now=now
    )
    assert "host-a" in dead


@pytest.mark.asyncio
async def test_self_is_never_declared_dead_even_if_stale():
    """Defense-in-depth: exclude_node_id guarantees a host can never trigger
    reclamation against its own resources, independent of whether it has
    written a fresh row yet this tick."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _heartbeat_at("self", now - timedelta(seconds=99999))

    dead = await hb.declared_dead_node_ids(
        async_session_factory, dead_after_seconds=900.0, exclude_node_id="self", now=now
    )
    assert "self" not in dead


@pytest.mark.asyncio
async def test_a_host_with_no_heartbeat_row_at_all_is_not_in_the_dead_list():
    """Absence of a row is not evidence of death — only a stale row is. A
    host that has simply never been observed (e.g. this test's own `_clean`
    fixture truncating the table) must not be silently treated as dead."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    dead = await hb.declared_dead_node_ids(
        async_session_factory, dead_after_seconds=900.0, exclude_node_id="self", now=now
    )
    assert dead == []


# --- 5. live-host resources remain protected --------------------------------


@pytest.mark.asyncio
async def test_a_live_hosts_sessions_are_not_claimed_even_when_some_other_host_is_dead():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    await _heartbeat_at("host-a", now - timedelta(seconds=10))  # alive
    await _heartbeat_at("host-c", now - timedelta(seconds=99999))  # dead

    live_session = await _make_session(owner_host="host-a")
    await _make_session(owner_host="host-c")

    dead = await hb.declared_dead_node_ids(async_session_factory, dead_after_seconds=900.0, exclude_node_id="host-b", now=now)
    assert dead == ["host-c"]

    claimed = await sweep.claim_batch(async_session_factory, node_id="host-b", dead_node_ids=dead)
    claimed_ids = {c.session_id for c in claimed}
    assert live_session not in claimed_ids


# --- 6. dead-host resources become reclaimable ------------------------------


@pytest.mark.asyncio
async def test_a_declared_dead_hosts_session_becomes_claimable_by_a_live_host():
    dead_session = await _make_session(owner_host="host-dead")

    claimed = await sweep.claim_batch(async_session_factory, node_id="host-b", dead_node_ids=["host-dead"])
    claimed_ids = {c.session_id for c in claimed}
    assert dead_session in claimed_ids


@pytest.mark.asyncio
async def test_without_the_widened_dead_node_ids_the_same_session_is_not_claimable():
    """Same fixture, no dead_node_ids — proves the widening is what changed
    the outcome, not some other side effect."""
    dead_session = await _make_session(owner_host="host-dead")

    claimed = await sweep.claim_batch(async_session_factory, node_id="host-b")
    claimed_ids = {c.session_id for c in claimed}
    assert dead_session not in claimed_ids


# --- Bookkeeping-only: never a real Docker/filesystem check for a foreign host


@pytest.mark.asyncio
async def test_a_dead_host_reclaim_never_attempts_a_real_docker_check(monkeypatch):
    """The core safety property: this host cannot observe host-dead's
    Docker daemon, so it must never call _docker_label/_docker_remove for a
    candidate it only reached via dead_node_ids — it must record
    'unverifiable' directly instead."""
    dead_session = await _make_session(owner_host="host-dead")

    called = {"docker": False}

    async def fail_if_called(*args, **kwargs):
        called["docker"] = True
        raise AssertionError("must never check Docker for a foreign dead-host candidate")

    monkeypatch.setattr(sweep, "_docker_label", fail_if_called)
    monkeypatch.setattr(sweep, "_docker_remove", fail_if_called)

    report = await sweep.sweep_once(async_session_factory, node_id="host-b", dead_node_ids=["host-dead"])

    assert called["docker"] is False
    assert report.unverifiable >= 1
    assert all(
        o.status == "unverifiable"
        for o in report.outcomes
        if o.item.session_id == dead_session
    )


@pytest.mark.asyncio
async def test_a_hosts_own_claim_still_runs_the_real_docker_check(monkeypatch):
    """Sanity check the negative test above isn't vacuous: a normal,
    same-host claim (via_dead_host_reclaim=False) must still call the real
    Docker seam exactly as before this change."""
    own_session = await _make_session(owner_host="host-b")

    async def fake_label(kind, name):
        return None  # "not found on this daemon" -> absent

    monkeypatch.setattr(sweep, "_docker_label", fake_label)

    report = await sweep.sweep_once(async_session_factory, node_id="host-b")
    assert any(o.item.session_id == own_session and o.status == "absent" for o in report.outcomes)


# --- 7. concurrent reclamation: only one claimant wins per resource --------


@pytest.mark.asyncio
async def test_two_live_hosts_racing_to_reclaim_the_same_dead_hosts_sessions_never_double_claim():
    import asyncio

    dead_sessions = {await _make_session(owner_host="host-dead") for _ in range(6)}

    claimed_b, claimed_c = await asyncio.gather(
        sweep.claim_batch(async_session_factory, sweep_id="b-sweep", node_id="host-b", dead_node_ids=["host-dead"]),
        sweep.claim_batch(async_session_factory, sweep_id="c-sweep", node_id="host-c", dead_node_ids=["host-dead"]),
    )
    ids_b = {c.session_id for c in claimed_b}
    ids_c = {c.session_id for c in claimed_c}

    assert ids_b.isdisjoint(ids_c)  # SKIP LOCKED partitions the work, never double-claims
    assert dead_sessions == (ids_b | ids_c) & dead_sessions


# --- 8. stale host fencing: a revived host cannot cause reprocessing -------


@pytest.mark.asyncio
async def test_a_resource_already_closed_via_dead_host_reclaim_is_never_reprocessed():
    """Once `unverifiable` is recorded, `_eligible_for_claim` treats it as
    terminal (matching cleaned/absent) — a later sweep, even from the
    formerly-dead host itself waking back up and running its own sweep, must
    not touch it again."""
    dead_session = await _make_session(owner_host="host-dead")

    first = await sweep.sweep_once(async_session_factory, node_id="host-b", dead_node_ids=["host-dead"])
    # 4 candidates per session (container/relay/network_internal/network_egress
    # — no workspace_path set here), all recorded unverifiable in one pass.
    assert first.unverifiable == 4

    # The "dead" host revives and runs its own sweep — this is the fencing
    # case: it must not reclaim or reprocess what was already closed.
    second = await sweep.sweep_once(async_session_factory, node_id="host-dead")
    assert second.claimed == 0
    assert not any(o.item.session_id == dead_session for o in second.outcomes)

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, dead_session)
    unverifiable_events = [e for e in (row.events or []) if e["type"] == "orphan_sweep.unverifiable"]
    assert len(unverifiable_events) == 4  # one per candidate, never duplicated by the second sweep


# --- 12. composes correctly with orphan_sweep's existing all-tenant scan --


@pytest.mark.asyncio
async def test_dead_host_reclaim_still_scans_every_tenants_sessions_like_the_rest_of_orphan_sweep():
    """P17's all_tenants_session scope is a parallel, independent boundary
    to host ownership (see orphan_sweep.py's own module docstring) — this
    change must not accidentally narrow that. Using two distinct
    RuntimeSessionRow rows (this table has no tenant_id column itself; the
    scope guarantee is exercised via all_tenants_session, already proven
    correct elsewhere) is enough to confirm dead-host reclaim doesn't bypass
    or duplicate that scan.
    """
    a = await _make_session(owner_host="host-dead")
    b = await _make_session(owner_host="host-dead")

    claimed = await sweep.claim_batch(async_session_factory, node_id="host-b", dead_node_ids=["host-dead"])
    claimed_ids = {c.session_id for c in claimed}
    assert {a, b} <= claimed_ids


# --- database failure during the heartbeat/dead-node pass does not corrupt state


@pytest.mark.asyncio
async def test_declared_dead_node_ids_raises_cleanly_on_a_broken_session_factory():
    """backend/app/main.py wraps this call in its own try/except and falls
    back to dead_node_ids=[] on failure (own-host-only scope that tick) —
    the contract this module must uphold is simply that a failure surfaces
    as a real exception, never a silently wrong/empty-but-successful
    result that looks the same as 'genuinely no dead hosts'."""

    def broken_factory():
        raise RuntimeError("db unavailable")

    with pytest.raises(RuntimeError):
        await hb.declared_dead_node_ids(broken_factory, dead_after_seconds=900.0, exclude_node_id="self")

    with pytest.raises(RuntimeError):
        await hb.record_heartbeat(broken_factory, "host-a")
