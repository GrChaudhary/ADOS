"""
P16 — orphan_sweep.claim_batch's node_id filter (RuntimeSessionRow.owner_host).

THE GAP THIS CLOSES
--------------------
_process_docker can only ever check the LOCAL Docker daemon a sweeper process
can reach. A container genuinely alive on a *different* host is, from here,
indistinguishable from one that was correctly removed by its own teardown:
`_docker_label` returns None either way, and `_process_docker` reports
"absent" — a terminal status (see `_eligible_for_claim`), never reclaimed by
a later pass. Before this phase, `claim_batch` had no host affinity at all: a
sweeper on host A could claim, and durably mark "absent", a session that was
actually started on host B and is still alive and running there. That is a
real leak (the container never gets cleaned) recorded as a false "all clear"
in the audit trail.

These tests use real Postgres (matching test_orphan_sweep.py's own
convention) and monkeypatch `_docker_label`/`_docker_remove` at the module
seam, exactly like test_orphan_sweep.py already does for its own Docker-
independent decision-logic tests — no real multi-host Docker infrastructure
exists to test this against, and none is faked. What real Docker cannot
prove here is host reachability itself; that is out of scope for a unit test
and is stated as such in the P16 report.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from orchestrate.runtime import orphan_sweep as sweep


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


async def _make_session(*, owner_host, state: str = "completed") -> uuid.UUID:
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


def test_effective_node_id_falls_back_to_the_real_hostname_when_unconfigured():
    import socket

    assert sweep.effective_node_id("") == socket.gethostname()
    assert sweep.effective_node_id("explicit-node") == "explicit-node"


@pytest.mark.asyncio
async def test_a_sweeper_with_no_node_id_claims_regardless_of_owner_host():
    """Unchanged pre-P16 behavior: every existing caller that has not opted
    into host-scoping (node_id=None, the default) still claims everything —
    this is what keeps Model A/B single-host deployments working exactly as
    before."""
    a = await _make_session(owner_host="host-a")
    b = await _make_session(owner_host="host-b")
    n = await _make_session(owner_host=None)

    claimed = await sweep.claim_batch(async_session_factory)
    claimed_ids = {c.session_id for c in claimed}
    assert {a, b, n} <= claimed_ids


@pytest.mark.asyncio
async def test_a_sweeper_only_claims_its_own_host_and_ownerless_rows():
    host_a_session = await _make_session(owner_host="host-a")
    host_b_session = await _make_session(owner_host="host-b")
    legacy_session = await _make_session(owner_host=None)

    claimed = await sweep.claim_batch(async_session_factory, node_id="host-a")
    claimed_ids = {c.session_id for c in claimed}

    assert host_a_session in claimed_ids
    assert legacy_session in claimed_ids
    assert host_b_session not in claimed_ids


@pytest.mark.asyncio
async def test_a_different_hosts_session_is_never_marked_absent_by_the_wrong_sweeper(monkeypatch):
    """The concrete failure this closes: host A's sweeper must never durably
    record host B's genuinely-still-running container as 'absent'."""
    host_b_session = await _make_session(owner_host="host-b")

    async def fake_label(kind, name):
        # From host A's Docker daemon, host B's container is invisible --
        # exactly what a real cross-host deployment would observe.
        return None

    monkeypatch.setattr(sweep, "_docker_label", fake_label)

    report = await sweep.sweep_once(async_session_factory, node_id="host-a")
    assert report.claimed == 0
    assert not any(o.item.session_id == host_b_session for o in report.outcomes)

    async with async_session_factory() as db:
        row = await db.get(RuntimeSessionRow, host_b_session)
    event_types = {e.get("type") for e in (row.events or [])}
    assert "orphan_sweep.absent" not in event_types
    assert "orphan_sweep.claimed" not in event_types


@pytest.mark.asyncio
async def test_the_owning_hosts_sweeper_correctly_claims_and_can_clean_its_own_session(monkeypatch):
    host_b_session = await _make_session(owner_host="host-b")

    async def fake_label(kind, name):
        return None

    monkeypatch.setattr(sweep, "_docker_label", fake_label)

    report = await sweep.sweep_once(async_session_factory, node_id="host-b")
    assert report.claimed >= 1
    assert any(o.item.session_id == host_b_session and o.status == "absent" for o in report.outcomes)


@pytest.mark.asyncio
async def test_two_hosts_racing_concurrently_never_cross_claim_or_double_claim():
    """Real Postgres, real concurrent execution (asyncio.gather — the same
    rigor test_two_concurrent_sweeps_never_claim_the_same_resource already
    established as sufficient proof of SKIP LOCKED's correctness in this
    exact file's sibling module) racing host-A's and host-B's claim_batch
    against a shared pool of sessions owned by both hosts plus legacy
    ownerless rows. Proves the node_id filter and the pre-existing SKIP
    LOCKED claim guard compose correctly under a real race, not just
    sequentially."""
    import asyncio

    host_a_sessions = {await _make_session(owner_host="host-a") for _ in range(5)}
    host_b_sessions = {await _make_session(owner_host="host-b") for _ in range(5)}
    legacy_sessions = {await _make_session(owner_host=None) for _ in range(5)}

    claimed_a, claimed_b = await asyncio.gather(
        sweep.claim_batch(async_session_factory, sweep_id="host-a-sweep", node_id="host-a"),
        sweep.claim_batch(async_session_factory, sweep_id="host-b-sweep", node_id="host-b"),
    )
    sessions_a = {c.session_id for c in claimed_a}
    sessions_b = {c.session_id for c in claimed_b}

    # No cross-host claim, under a real race.
    assert sessions_a.isdisjoint(host_b_sessions)
    assert sessions_b.isdisjoint(host_a_sessions)
    # No double-claim of the same session by both sweepers.
    assert sessions_a.isdisjoint(sessions_b)
    # Every host-owned session was claimed by its own host.
    assert host_a_sessions <= sessions_a
    assert host_b_sessions <= sessions_b
    # Legacy ownerless rows were claimed by exactly one of the two (SKIP
    # LOCKED partitions them; either sweeper is a correct outcome).
    assert legacy_sessions == (sessions_a | sessions_b) & legacy_sessions
    assert (sessions_a & legacy_sessions).isdisjoint(sessions_b & legacy_sessions)


@pytest.mark.asyncio
async def test_a_still_unclaimed_cross_host_session_remains_claimable_by_its_own_host_later(monkeypatch):
    """The negative case above must not leave the row permanently stuck --
    host A skipping it is a no-op, not a terminal outcome."""
    host_b_session = await _make_session(owner_host="host-b")

    async def fake_label(kind, name):
        return None

    monkeypatch.setattr(sweep, "_docker_label", fake_label)

    await sweep.sweep_once(async_session_factory, node_id="host-a")
    report = await sweep.sweep_once(async_session_factory, node_id="host-b")
    assert any(o.item.session_id == host_b_session and o.status == "absent" for o in report.outcomes)
