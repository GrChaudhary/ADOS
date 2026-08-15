"""
P12 -- distributed admission control, proven with REAL, separate OS
processes against the REAL Postgres database, not asyncio.gather inside one
process (backend/tests/test_admission_control_global.py already covers that
tier). This is the acceptance evidence P12's own instructions asked for:

    "Use at least two independent OS processes against the same Postgres
    database... Do not accept 'no exception occurred' as evidence. Use
    exact admitted/rejected counts."

WHAT THIS PROVES, IN ORDER
----------------------------
PART 1 -- reproduces the gap exactly as it shipped in P11: each of N
    separate OS processes constructs its own in-process-only
    AdmissionControl (session_factory=None, matching what
    integrations/admission_control.py was before this phase) and races to
    acquire a capability slot against a configured limit. Expected, and
    shown: each process independently admits up to the limit -- total
    admitted across all N processes is N x limit, not limit. This is run
    first specifically so the "after" result below is a comparison against
    a demonstrated failure, not an assertion nobody checked against reality.

PART 2 -- the fix: same N processes, same limit, but AdmissionControl is
    now wired with session_factory=async_session_factory (real Postgres).
    Expected, and shown: total admitted across ALL processes together is
    exactly `limit`, regardless of N.

PART 3 -- the other two P11 gates (approval-queue depth, per-session
    activity) were ALREADY Postgres-advisory-lock / row-lock serialized
    (backend/app/mcp_gateway.py) -- genuinely cross-process by construction,
    since a database lock is not a property of any one client process. This
    part proves that with two real OS processes each calling the real
    `request_capability` MCP tool function (not a reimplementation),
    against a shared mission/session, exactly matching a real multi-process
    deployment's request pattern.

PART 4 -- process crash: one worker acquires a global lease and is then
    SIGKILLed before it releases (simulating an ADOS process dying
    mid-execution). Shows the lease row is NOT cleaned up by anything
    automatic in the moment (a real leak, as designed), then runs the same
    periodic reclaim pass backend/app/main.py's scheduler calls and shows
    it removes exactly that lease and nothing else.

Every part reports attempted / admitted / rejected / max concurrent /
duration -- exact counts, not "no exception occurred."

No ServiceNow, no Docker containers -- this is admission control specifically.
Standalone script, never pytest-collected (matches scripts/p9_crash_recovery_
e2e.py / scripts/p11_orphan_recovery_exercise.py's own convention).

Usage:
    python scripts/p12_multiprocess_admission_proof.py
"""

import asyncio
import multiprocessing as mp
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text  # noqa: E402

from db.engine import async_session_factory  # noqa: E402
from db.models.admission_lease import AdmissionLeaseRow  # noqa: E402
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow  # noqa: E402


def _print_header(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


async def _cleanup_admission_state() -> None:
    async with async_session_factory() as db:
        await db.execute(delete(AdmissionLeaseRow))
        await db.commit()


# --- PART 1 / PART 2 workers ---------------------------------------------------
#
# Admission control bounds CONCURRENT holders, not a lifetime total -- a
# worker that acquires, releases, and re-acquires can legitimately rack up
# more total admits than the limit over time without ever violating it. To
# measure the thing that actually matters ("simultaneous admission" per this
# phase's own instructions), every worker below attempts EXACTLY ONCE, all
# workers are released to attempt at the same instant via a real
# multiprocessing.Barrier (not a hopeful sleep), and — if admitted — holds
# the slot until a second barrier releases every worker to attempt release
# AT THE SAME INSTANT too ("simultaneous release", also explicitly asked
# for). This makes "total admitted across all workers" and "peak concurrent
# admitted" the same number by construction, so the assertion below is
# actually measuring what it claims to.


def _capability_gate_worker(*, use_global: bool, limit: int, acquire_barrier, release_barrier, result_queue) -> None:
    """Runs in its own OS process (multiprocessing, spawn context -- a fresh
    Python interpreter, its own asyncio event loop, its own DB connections;
    nothing shared with the parent or sibling workers except the Postgres
    server itself)."""

    async def _run():
        from integrations.admission_control import AdmissionControl

        ac = AdmissionControl(
            max_concurrent_capability_executions=limit,
            session_factory=async_session_factory if use_global else None,
        )
        acquire_barrier.wait(timeout=30)  # every process attempts at the same instant
        t0 = time.monotonic()
        if use_global:
            lease = await ac.try_acquire_capability_slot_global()
            ok = lease is not None
        else:
            ok = ac.try_acquire_capability_slot()
        acquire_latency = time.monotonic() - t0

        release_barrier.wait(timeout=30)  # every admitted process releases at the same instant
        if ok:
            if use_global:
                await ac.release_capability_slot_global(lease)
            else:
                ac.release_capability_slot()
        return ok, acquire_latency

    admitted, acquire_latency = asyncio.run(_run())
    result_queue.put({"pid": os.getpid(), "admitted": admitted, "acquire_latency": acquire_latency})


def _run_multiprocess_capability_gate(*, use_global: bool, n_processes: int, limit: int):
    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    acquire_barrier = ctx.Barrier(n_processes)
    release_barrier = ctx.Barrier(n_processes)
    procs = []
    started = time.monotonic()
    for _ in range(n_processes):
        p = ctx.Process(
            target=_capability_gate_worker,
            kwargs=dict(use_global=use_global, limit=limit, acquire_barrier=acquire_barrier, release_barrier=release_barrier, result_queue=result_queue),
        )
        p.start()
        procs.append(p)
    for p in procs:
        p.join(timeout=60)
    duration = time.monotonic() - started

    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    total_admitted = sum(1 for r in results if r["admitted"])
    total_rejected = sum(1 for r in results if not r["admitted"])
    return results, total_admitted, total_rejected, duration


# --- PART 3 workers (approval_queue / session_activity, real request_capability) --


def _mcp_tool_worker(*, token: str, capability: str, arguments: dict, attempts: int, result_queue) -> None:
    async def _run():
        from unittest.mock import patch

        from backend.app import mcp_gateway
        from backend.app.mcp_gateway import request_capability

        statuses = []
        with patch.object(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}):
            for i in range(attempts):
                # Distinct arguments per attempt: the canonical idempotency
                # key (session, capability, arguments) would otherwise
                # replay attempt 2+ as the same logical request as attempt 1
                # and never actually exercise the gate repeatedly.
                call_args = {**arguments, "summary": f"{arguments.get('summary', 'x')} #{os.getpid()}-{i}"}
                answer = await request_capability.fn(capability, call_args)
                statuses.append(answer["status"])
        return statuses

    statuses = asyncio.run(_run())
    result_queue.put({"pid": os.getpid(), "statuses": statuses})


async def _setup_mission_and_sessions(n_sessions: int, capability: str):
    from backend.app.mcp_gateway import hash_token
    from orchestrate.runtime.prime import token_expiry

    async with async_session_factory() as db:
        mission = MissionRow(
            title="p12 multiprocess admission proof", objective="o", domain="it",
            allowed_capabilities=[capability], status="running",
        )
        db.add(mission)
        await db.flush()
        tokens = []
        for _ in range(n_sessions):
            token = "tok-" + os.urandom(16).hex()
            db.add(RuntimeSessionRow(
                mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
                token_expires_at=token_expiry(1800.0),
            ))
            tokens.append(token)
        await db.commit()
        return mission.mission_id, tokens


async def _teardown_mission(mission_id) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(CapabilityRequestRow).where(CapabilityRequestRow.mission_id == mission_id))
        await db.execute(delete(RuntimeSessionRow).where(RuntimeSessionRow.mission_id == mission_id))
        await db.execute(delete(MissionRow).where(MissionRow.mission_id == mission_id))
        await db.commit()


# --- PART 4: process crash / reclaim -------------------------------------------


def _crash_worker(*, ready_event, hold_seconds: float) -> None:
    async def _run():
        from integrations.admission_control import AdmissionControl

        ac = AdmissionControl(max_concurrent_capability_executions=5, session_factory=async_session_factory)
        lease = await ac.try_acquire_capability_slot_global()
        assert lease is not None
        ready_event.set()
        await asyncio.sleep(hold_seconds)  # never reaches release -- killed first

    asyncio.run(_run())


async def _main() -> None:
    print(f"Started {datetime.now(timezone.utc).isoformat()}")
    await _cleanup_admission_state()

    # PART 1 -----------------------------------------------------------------
    _print_header("PART 1 -- reproducing the P11 gap: process-local counters, 6 real OS processes attempting SIMULTANEOUSLY")
    LIMIT = 3
    N_PROC = 6
    results, admitted, rejected, duration = _run_multiprocess_capability_gate(
        use_global=False, n_processes=N_PROC, limit=LIMIT,
    )
    print(f"configured limit={LIMIT}, processes={N_PROC} (each attempts exactly once, all at the same instant)")
    for r in results:
        print(f"  pid={r['pid']}: admitted={r['admitted']} acquire_latency={r['acquire_latency']*1000:.1f}ms")
    print(f"TOTAL: attempted={N_PROC} admitted={admitted} rejected={rejected} maximum_concurrent={admitted} duration={duration:.2f}s")
    if admitted > LIMIT:
        print(f"CONFIRMED GAP: {admitted} admitted simultaneously against a configured limit of {LIMIT} "
              f"-- each process enforced its own local ceiling independently and never saw the others.")
    else:
        print("UNEXPECTED: gap did not reproduce (admitted <= limit) -- investigate before trusting Part 2.")

    await _cleanup_admission_state()

    # PART 2 -----------------------------------------------------------------
    _print_header("PART 2 -- the fix: Postgres-backed global admission, same 6 real OS processes attempting SIMULTANEOUSLY")
    results, admitted, rejected, duration = _run_multiprocess_capability_gate(
        use_global=True, n_processes=N_PROC, limit=LIMIT,
    )
    print(f"configured limit={LIMIT}, processes={N_PROC} (each attempts exactly once, all at the same instant)")
    for r in results:
        print(f"  pid={r['pid']}: admitted={r['admitted']} acquire_latency={r['acquire_latency']*1000:.1f}ms")
    print(f"TOTAL: attempted={N_PROC} admitted={admitted} rejected={rejected} maximum_concurrent={admitted} duration={duration:.2f}s")
    assert admitted == LIMIT, f"FAIL: expected exactly {LIMIT} admitted globally, got {admitted}"
    print(f"PASS: exactly {LIMIT} admitted simultaneously across {N_PROC} real processes attempting at the same "
          f"instant -- the global ceiling held even though local, in-process logic would have admitted all {N_PROC}.")

    async with async_session_factory() as db:
        leftover = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert leftover == [], f"FAIL: {len(leftover)} lease rows leaked after all workers released"
    print("Independently verified in Postgres: zero admission_leases rows remain after release.")

    # PART 3 -----------------------------------------------------------------
    _print_header("PART 3 -- approval_queue / session_activity gates, real request_capability, 2 real OS processes")

    # Set via environment, not by mutating the in-process Settings singleton:
    # workers are spawned (fresh interpreter, fresh Settings() import) via
    # multiprocessing's "spawn" context specifically so they behave like two
    # genuinely separate ADOS processes, not two threads sharing memory --
    # mutating this process's settings object would have no effect on them.
    # `spawn` children inherit the parent's os.environ at spawn time, which
    # pydantic-settings' BaseSettings reads on construction.
    EXPENSIVE = {"summary": "root cause", "_estimated_cost_usd": 300_000.0}  # parks -> approval_queue gate
    APPROVAL_LIMIT = 3
    os.environ["MAX_PENDING_APPROVALS"] = str(APPROVAL_LIMIT)
    try:
        mission_id, tokens = await _setup_mission_and_sessions(2, "NotifyITHelpdesk")
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue()
        procs = [
            ctx.Process(target=_mcp_tool_worker, kwargs=dict(
                token=tokens[i], capability="NotifyITHelpdesk", arguments=EXPENSIVE, attempts=4, result_queue=result_queue,
            ))
            for i in range(2)
        ]
        started = time.monotonic()
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        duration = time.monotonic() - started

        results = []
        while not result_queue.empty():
            results.append(result_queue.get())
        all_statuses = [s for r in results for s in r["statuses"]]
        parked = sum(1 for s in all_statuses if s == "pending_approval")
        denied = sum(1 for s in all_statuses if s == "denied")
        print(f"approval_queue: configured limit={APPROVAL_LIMIT}, processes=2, attempts/process=4")
        for r in results:
            print(f"  pid={r['pid']}: {r['statuses']}")
        print(f"TOTAL: attempted={len(all_statuses)} parked(admitted)={parked} denied(rejected)={denied} duration={duration:.2f}s")
        assert parked == APPROVAL_LIMIT, f"FAIL: expected exactly {APPROVAL_LIMIT} parked, got {parked}"
        print(f"PASS: exactly {APPROVAL_LIMIT} requests parked globally across 2 real processes, "
              f"despite {len(all_statuses)} total real MCP tool calls.")
    finally:
        del os.environ["MAX_PENDING_APPROVALS"]
        await _teardown_mission(mission_id)

    # session_activity: one shared session, two processes hammering IT specifically
    SESSION_LIMIT = 3
    os.environ["MAX_CAPABILITY_REQUESTS_PER_SESSION"] = str(SESSION_LIMIT)
    try:
        mission_id, tokens = await _setup_mission_and_sessions(1, "NotifyITHelpdesk")
        shared_token = tokens[0]
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue()
        procs = [
            ctx.Process(target=_mcp_tool_worker, kwargs=dict(
                # EXPENSIVE, not a plain autonomous-tier call: guarantees
                # every attempt parks (Tier 2) rather than risking a real
                # connector call if SERVICENOW_* happens to be configured on
                # this machine from other testing -- this gate's own check
                # runs before the tier decision either way, so it exercises
                # the same code regardless.
                token=shared_token, capability="NotifyITHelpdesk", arguments=dict(EXPENSIVE), attempts=4, result_queue=result_queue,
            ))
            for _ in range(2)
        ]
        started = time.monotonic()
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
        duration = time.monotonic() - started

        results = []
        while not result_queue.empty():
            results.append(result_queue.get())
        all_statuses = [s for r in results for s in r["statuses"]]
        admitted = sum(1 for s in all_statuses if s not in ("denied",))
        denied = sum(1 for s in all_statuses if s == "denied")
        print(f"\nsession_activity: configured limit={SESSION_LIMIT}, processes=2 (SAME session), attempts/process=4")
        for r in results:
            print(f"  pid={r['pid']}: {r['statuses']}")
        print(f"TOTAL: attempted={len(all_statuses)} admitted={admitted} denied(rejected)={denied} duration={duration:.2f}s")
        assert admitted == SESSION_LIMIT, f"FAIL: expected exactly {SESSION_LIMIT} admitted, got {admitted}"
        print(f"PASS: exactly {SESSION_LIMIT} requests admitted globally for one shared session "
              f"across 2 real processes calling it simultaneously.")
    finally:
        del os.environ["MAX_CAPABILITY_REQUESTS_PER_SESSION"]
        await _teardown_mission(mission_id)

    # PART 4 -----------------------------------------------------------------
    _print_header("PART 4 -- process crash: a lease held by a killed process, then reclaimed")
    await _cleanup_admission_state()
    ctx = mp.get_context("spawn")
    ready_event = ctx.Event()
    p = ctx.Process(target=_crash_worker, kwargs=dict(ready_event=ready_event, hold_seconds=30.0))
    p.start()
    got_ready = ready_event.wait(timeout=10)
    assert got_ready, "FAIL: worker never signalled it had acquired the lease"
    async with async_session_factory() as db:
        rows = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert len(rows) == 1, f"FAIL: expected exactly 1 lease row held by the live worker, found {len(rows)}"
    print(f"Worker pid={p.pid} confirmed holding 1 lease. Sending SIGKILL (simulating a real process crash)...")
    os.kill(p.pid, signal.SIGKILL)
    p.join(timeout=10)
    assert not p.is_alive(), "FAIL: worker still alive after SIGKILL"

    async with async_session_factory() as db:
        rows = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert len(rows) == 1, "FAIL: the lease row must still exist immediately after the crash -- nothing releases it automatically"
    print("Confirmed: the lease row survives the crash untouched (nothing releases it automatically) -- a real leak, as designed.")

    from orchestrate.runtime.admission_lease_reclaim import reclaim_stale_admission_state
    report = await reclaim_stale_admission_state(async_session_factory, lease_max_age_seconds=0.0)
    print(f"Ran the same periodic reclaim pass backend/app/main.py's scheduler calls: leases_reclaimed={report.leases_reclaimed}")
    assert report.leases_reclaimed == 1

    async with async_session_factory() as db:
        rows = (await db.execute(select(AdmissionLeaseRow))).scalars().all()
    assert rows == [], "FAIL: lease row should be gone after reclaim"
    print("Independently re-verified in Postgres: zero lease rows remain after reclaim.")

    _print_header("ALL PARTS PASSED")


if __name__ == "__main__":
    asyncio.run(_main())
