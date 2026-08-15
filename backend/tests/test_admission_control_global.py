"""
P12 — the Postgres-backed global layer admission_control.py added on top of
P11's in-process counters (integrations/admission_control.py), plus the
mission-start rate limiter (integrations/rate_limiter.py) and the periodic
reclaim pass for both (orchestrate/runtime/admission_lease_reclaim.py).

WHAT THIS FILE PROVES
----------------------
* `session_factory=None` (every P11 test, unchanged) still behaves exactly
  as before — the global layer is purely additive.
* With a real session_factory, below/at/over limit is enforced against real
  Postgres, and a rejected global acquire releases the local slot it had
  already taken.
* A REAL concurrent race (asyncio.gather, real Postgres transactions, not a
  sequential simulation) cannot push the admitted count past the configured
  global limit — the same evidence bar P11's own concurrent-race tests used
  for the two DB-backed mcp_gateway.py gates.
* The rate limiter admits up to its configured max within a window and
  refuses beyond it; `limit<=0` disables it.
* The periodic reclaim pass removes leases/events older than their
  configured max age and leaves fresher ones alone.

Real Postgres throughout — no mocking of the database in any test here.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select, text

from db.engine import async_session_factory
from db.models.admission_lease import AdmissionLeaseRow
from db.models.rate_limit_event import RateLimitEventRow
from integrations.admission_control import AdmissionControl
from integrations.rate_limiter import RateLimiter
from orchestrate.runtime.admission_lease_reclaim import reclaim_stale_admission_state


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE admission_leases, rate_limit_events CASCADE"))
        await db.commit()
    yield


# --- AdmissionControl global layer -------------------------------------------


async def test_global_disabled_without_a_session_factory_matches_p11_exactly():
    ac = AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1)
    assert ac.globally_coordinated is False
    assert await ac.try_acquire_capability_slot_global() is None
    # None means "not applicable", not "rejected" -- callers must gate on
    # globally_coordinated before treating a None lease as a refusal, which
    # is exactly what hub.py does.


async def test_global_below_and_at_limit_allowed():
    ac = AdmissionControl(
        max_concurrent_capability_executions=2, max_concurrent_missions=1,
        session_factory=async_session_factory,
    )
    assert ac.globally_coordinated is True
    lease1 = await ac.try_acquire_capability_slot_global()
    lease2 = await ac.try_acquire_capability_slot_global()
    assert lease1 is not None and lease2 is not None
    assert lease1 != lease2

    async with async_session_factory() as db:
        count = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert len(count) == 2


async def test_global_over_limit_refused_and_never_creates_a_row():
    ac = AdmissionControl(
        max_concurrent_capability_executions=1, max_concurrent_missions=1,
        session_factory=async_session_factory,
    )
    lease1 = await ac.try_acquire_capability_slot_global()
    assert lease1 is not None
    lease2 = await ac.try_acquire_capability_slot_global()
    assert lease2 is None, "a second lease must be refused at limit=1"

    async with async_session_factory() as db:
        rows = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert len(rows) == 1, "a refused acquire must never leave a row behind"


async def test_global_release_frees_the_slot_and_deletes_the_row():
    ac = AdmissionControl(
        max_concurrent_capability_executions=1, max_concurrent_missions=1,
        session_factory=async_session_factory,
    )
    lease1 = await ac.try_acquire_capability_slot_global()
    assert await ac.try_acquire_capability_slot_global() is None

    await ac.release_capability_slot_global(lease1)

    async with async_session_factory() as db:
        rows = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert rows == []

    lease2 = await ac.try_acquire_capability_slot_global()
    assert lease2 is not None


async def test_capability_and_mission_gates_use_independent_advisory_locks():
    """Both gates share the same table but a different `gate` value --
    exhausting one must never affect the other's ceiling."""
    ac = AdmissionControl(
        max_concurrent_capability_executions=1, max_concurrent_missions=1,
        session_factory=async_session_factory,
    )
    assert await ac.try_acquire_capability_slot_global() is not None
    assert await ac.try_acquire_mission_slot_global() is not None
    assert await ac.try_acquire_capability_slot_global() is None
    assert await ac.try_acquire_mission_slot_global() is None


async def test_real_concurrent_race_cannot_bypass_the_global_limit():
    """The actual acceptance evidence: N real asyncio tasks, each opening
    its own Postgres transaction via the shared session_factory (exactly
    how two separate OS processes would each open their own), racing for a
    limit far smaller than N. Peak admitted must equal the configured
    limit exactly, not "close to it"."""
    limit = 3
    concurrency = 12
    ac = AdmissionControl(
        max_concurrent_capability_executions=limit, max_concurrent_missions=1,
        session_factory=async_session_factory,
    )

    results = await asyncio.gather(*[ac.try_acquire_capability_slot_global() for _ in range(concurrency)])
    admitted = [r for r in results if r is not None]
    rejected = [r for r in results if r is None]

    assert len(admitted) == limit, f"expected exactly {limit} admitted, got {len(admitted)}"
    assert len(rejected) == concurrency - limit

    async with async_session_factory() as db:
        rows = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert len(rows) == limit, "the database's own row count must match the admitted count exactly"


# --- RateLimiter --------------------------------------------------------------


async def test_rate_limiter_disabled_without_a_session_factory():
    rl = RateLimiter()
    assert rl.enabled is False
    for _ in range(5):
        assert await rl.try_admit_mission_start(limit=1, window_seconds=60) is True


async def test_rate_limiter_disabled_when_limit_non_positive():
    rl = RateLimiter(session_factory=async_session_factory)
    assert rl.enabled is True
    for _ in range(5):
        assert await rl.try_admit_mission_start(limit=0, window_seconds=60) is True

    async with async_session_factory() as db:
        rows = (await db.execute(select(RateLimitEventRow))).scalars().all()
    assert rows == [], "a disabled (limit<=0) limiter must not even record an event"


async def test_rate_limiter_admits_up_to_the_limit_then_refuses():
    rl = RateLimiter(session_factory=async_session_factory)
    assert await rl.try_admit_mission_start(limit=2, window_seconds=60) is True
    assert await rl.try_admit_mission_start(limit=2, window_seconds=60) is True
    assert await rl.try_admit_mission_start(limit=2, window_seconds=60) is False

    async with async_session_factory() as db:
        rows = (await db.execute(select(RateLimitEventRow))).scalars().all()
    assert len(rows) == 2, "a refused start must not record an event"


async def test_rate_limiter_real_concurrent_race_cannot_bypass_the_window_limit():
    limit = 4
    concurrency = 15
    rl = RateLimiter(session_factory=async_session_factory)

    results = await asyncio.gather(
        *[rl.try_admit_mission_start(limit=limit, window_seconds=60) for _ in range(concurrency)]
    )
    assert sum(1 for r in results if r) == limit
    assert sum(1 for r in results if not r) == concurrency - limit


async def test_rate_limiter_ignores_events_outside_the_window():
    """A caller supplying a very small window must not see events from
    outside it counted against the limit."""
    rl = RateLimiter(session_factory=async_session_factory)
    async with async_session_factory() as db:
        db.add(RateLimitEventRow(limiter="mission_start_rate"))
        await db.commit()

    # A 0-second-wide window (relative to a row committed moments ago) --
    # the existing row is already outside it.
    assert await rl.try_admit_mission_start(limit=1, window_seconds=0.001) is True


# --- Periodic reclaim ----------------------------------------------------------


async def test_reclaim_removes_only_leases_older_than_max_age():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        db.add(AdmissionLeaseRow(gate="capability_concurrency", acquired_at=now - timedelta(seconds=100)))
        db.add(AdmissionLeaseRow(gate="capability_concurrency", acquired_at=now - timedelta(seconds=10)))
        await db.commit()

    report = await reclaim_stale_admission_state(
        async_session_factory, lease_max_age_seconds=50.0, rate_limit_event_retention_seconds=3600.0, now=now,
    )
    assert report.leases_reclaimed == 1

    async with async_session_factory() as db:
        remaining = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].acquired_at == now - timedelta(seconds=10)


async def test_reclaim_prunes_only_rate_limit_events_older_than_retention():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        db.add(RateLimitEventRow(limiter="mission_start_rate", occurred_at=now - timedelta(seconds=7200)))
        db.add(RateLimitEventRow(limiter="mission_start_rate", occurred_at=now - timedelta(seconds=10)))
        await db.commit()

    report = await reclaim_stale_admission_state(
        async_session_factory, lease_max_age_seconds=1800.0, rate_limit_event_retention_seconds=3600.0, now=now,
    )
    assert report.rate_limit_events_pruned == 1

    async with async_session_factory() as db:
        remaining = (await db.execute(select(RateLimitEventRow))).scalars().all()
    assert len(remaining) == 1
