"""
P12 -- Docker resource ownership, proven with REAL Docker and REAL Postgres,
using two genuinely separate OS processes racing on the same claim, plus the
independent Docker-label re-verification orphan_sweep.py already performs
before every delete.

The claim/lease/ownership-label mechanism itself is NOT new here -- P7-C
built it, and this phase's own instructions say plainly: "Use the existing
ownership labels, claim leases, and reconciliation mechanisms where
applicable. Do not create a second ownership system." This script's job is
to independently verify, against real infrastructure, that the four cases
P12 named actually hold:

  A. owner protection    -- a second claim attempt within the lease window
                             gets nothing, even though the resource still
                             exists and is nameable.
  B. legitimate recovery  -- a still-LIVE session (not terminal, not
                             orphan-marked) is never claimable at all --
                             recovery only ever happens through the real
                             reconciliation state transition, never by
                             directly sweeping a running session.
  C. simultaneous recovery -- two REAL OS processes calling claim_batch at
                             the exact same instant against the SAME
                             orphaned session row: exactly one claims it.
  D. stale-row protection  -- a DB row claiming a session id that does NOT
                             match what is actually labelled on the live
                             Docker resource is refused, not deleted.

Real Docker resources throughout (one lightweight `alpine sleep` container
per case, not a full Prime Agent runtime -- orphan_sweep.py's own claim/
verify/delete logic only ever inspects labels, never what is running
inside, so this is the same code path P11's own recovery exercise already
proved once against the real Prime Agent image).

Usage:
    python scripts/p12_docker_ownership_proof.py
"""

import asyncio
import multiprocessing as mp
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from db.engine import async_session_factory  # noqa: E402
from db.models.mission import MissionRow, RuntimeSessionRow  # noqa: E402
from db.tenancy import use_all_tenants  # noqa: E402
from orchestrate.runtime.egress import LABEL_COMPONENT, LABEL_MANAGED_BY, LABEL_MANAGED_BY_VALUE, LABEL_SESSION  # noqa: E402

IMAGE = "alpine:latest"


def _print_header(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def _sh(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stdout} {result.stderr}")
    return result.stdout.strip()


def _ensure_image() -> None:
    have = _sh("docker", "images", "-q", IMAGE, check=False)
    if not have:
        print(f"Pulling {IMAGE} (one-time, small)...")
        _sh("docker", "pull", IMAGE)


def _create_real_container(*, session_id: uuid.UUID, name: str) -> None:
    _sh(
        "docker", "run", "-d", "--name", name,
        "--label", f"{LABEL_SESSION}={session_id}",
        "--label", f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
        "--label", f"{LABEL_COMPONENT}=prime_container",
        IMAGE, "sleep", "600",
    )


def _container_exists(name: str) -> bool:
    out = _sh("docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}", check=False)
    return name in out.splitlines()


def _remove_container_if_present(name: str) -> None:
    _sh("docker", "rm", "-f", name, check=False)


async def _make_session_row(*, state: str, container_name: str, orphaned: bool) -> uuid.UUID:
    async with async_session_factory() as db:
        mission = MissionRow(title="p12 docker ownership proof", objective="o", domain="it", allowed_capabilities=[], status="failed")
        db.add(mission)
        await db.flush()
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state=state, container_name=container_name,
            failure_reason="orphaned: process abandoned before writing a terminal state" if orphaned else None,
        )
        db.add(sess)
        await db.commit()
        return sess.session_id


async def _cleanup_row(session_id: uuid.UUID) -> None:
    # P17 -- this driver process never resolves a tenant context (it isn't
    # testing tenancy); a plain verification/cleanup read needs the
    # explicit cross-tenant opt-out, same as every other live-proof script.
    with use_all_tenants():
        async with async_session_factory() as db:
            row = (await db.execute(select(RuntimeSessionRow).where(RuntimeSessionRow.session_id == session_id))).scalar_one_or_none()
            if row is None:
                return
            mission_id = row.mission_id
            await db.execute(delete(RuntimeSessionRow).where(RuntimeSessionRow.session_id == session_id))
            await db.execute(delete(MissionRow).where(MissionRow.mission_id == mission_id))
            await db.commit()


# --- Case C: simultaneous recovery ---------------------------------------------


def _claim_worker(*, barrier, result_queue) -> None:
    async def _run():
        from orchestrate.runtime.orphan_sweep import claim_batch

        barrier.wait(timeout=30)
        claimed = await claim_batch(async_session_factory, sweep_id=f"proof-{__import__('os').getpid()}")
        return len(claimed)

    n = asyncio.run(_run())
    result_queue.put({"pid": __import__("os").getpid(), "claimed_count": n})


def _run_simultaneous_claim(n_processes: int):
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(n_processes)
    result_queue = ctx.Queue()
    procs = [ctx.Process(target=_claim_worker, kwargs=dict(barrier=barrier, result_queue=result_queue)) for _ in range(n_processes)]
    started = time.monotonic()
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
    duration = time.monotonic() - started
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    return results, duration


async def _main() -> None:
    print(f"Started {datetime.now(timezone.utc).isoformat()}")
    _ensure_image()

    # --- Case B: a LIVE session is never claimable ------------------------------
    _print_header("CASE B -- a still-live (non-terminal) session must not be claimable at all")
    live_container = f"ados-prime-{uuid.uuid4().hex[:12]}"
    live_session_id = None
    try:
        live_session_id = await _make_session_row(state="running", container_name=live_container, orphaned=False)
        # No real Docker resource needed for this case -- claim_batch's own
        # WHERE clause (state must be terminal AND failure_reason must carry
        # the orphan marker) must exclude this row before Docker is ever
        # even asked about it.
        from orchestrate.runtime.orphan_sweep import claim_batch

        claimed = await claim_batch(async_session_factory, sweep_id="case-b-proof")
        claimed_this_session = [c for c in claimed if c.session_id == live_session_id]
        assert claimed_this_session == [], f"FAIL: a live, non-terminal session was claimed: {claimed_this_session}"
        print(f"PASS: live session {live_session_id} — state='running', no orphan marker — claimed 0 resources.")
    finally:
        if live_session_id:
            await _cleanup_row(live_session_id)

    # --- Case C: simultaneous recovery, exactly one claims ----------------------
    _print_header("CASE C -- two REAL OS processes claim_batch() at the exact same instant, same orphaned session")
    orphan_container = f"ados-prime-{uuid.uuid4().hex[:12]}"
    orphan_session_id = None
    try:
        orphan_session_id = await _make_session_row(state="failed", container_name=orphan_container, orphaned=True)
        # Labeled with the row's own real session id -- matches exactly what
        # a real teardown-that-never-ran would have left, since the real
        # creation path always labels with the session's own id.
        _create_real_container(session_id=orphan_session_id, name=orphan_container)

        results, duration = _run_simultaneous_claim(n_processes=3)
        for r in results:
            print(f"  pid={r['pid']}: claimed_count={r['claimed_count']}")
        total_claimed = sum(r["claimed_count"] for r in results)
        winners = [r for r in results if r["claimed_count"] > 0]
        print(f"TOTAL: processes=3, total_claims_across_all_processes={total_claimed}, duration={duration:.2f}s")
        assert len(winners) == 1, f"FAIL: expected exactly 1 process to claim something, got {len(winners)}"
        print(f"PASS: exactly 1 of 3 simultaneous real processes claimed this session's resources "
              f"(pid={winners[0]['pid']}, {winners[0]['claimed_count']} candidate(s)); the other 2 claimed 0.")

        # --- Case A: owner protection -- a further claim inside the lease window gets nothing
        _print_header("CASE A -- owner protection: a claim attempt within the lease window, after the winner above, gets nothing")
        from orchestrate.runtime.orphan_sweep import claim_batch

        again = await claim_batch(async_session_factory, sweep_id="case-a-late-comer")
        again_this_session = [c for c in again if c.session_id == orphan_session_id]
        assert again_this_session == [], f"FAIL: a resource already claimed within its lease was claimed again: {again_this_session}"
        print(f"PASS: a later claim attempt for the same session, still within the "
              f"{300.0:.0f}s lease window, claimed 0 -- the resource is still 'owned' by the first winner.")
        assert _container_exists(orphan_container), "the container itself is untouched by claiming alone (claim != delete)"
        print("Confirmed: claiming does not itself delete anything -- the real container is still present, "
              "exactly as process_claimed()/sweep_once() design separately (claim, then process, then finalize).")
    finally:
        _remove_container_if_present(orphan_container)
        if orphan_session_id:
            await _cleanup_row(orphan_session_id)

    # --- Case D: stale DB row must not authorize deleting a resource it does not actually own
    _print_header("CASE D -- a DB row's session id must match the LIVE Docker label before anything is deleted")
    real_owner_id = uuid.uuid4()
    mismatched_container = f"ados-prime-{uuid.uuid4().hex[:12]}"
    mismatched_session_id = None
    try:
        # The container is REALLY labeled with a DIFFERENT session id than
        # the DB row that will claim to own it -- simulating a stale/
        # incorrect row (e.g. a name collision, or a row whose real
        # container was already replaced by something else under the same
        # name -- the exact scenario LABEL_SESSION exists to catch, per
        # egress.py's own docstring).
        _create_real_container(session_id=real_owner_id, name=mismatched_container)
        mismatched_session_id = await _make_session_row(state="failed", container_name=mismatched_container, orphaned=True)

        from orchestrate.runtime.orphan_sweep import claim_batch, process_claimed

        claimed = await claim_batch(async_session_factory, sweep_id="case-d-proof")
        this_claim = [c for c in claimed if c.session_id == mismatched_session_id]
        assert len(this_claim) >= 1, "FAIL: setup problem -- the mismatched-row candidate was not even claimed"
        outcomes = await process_claimed(this_claim)
        container_outcome = next(o for o in outcomes if o.item.kind == "container")
        print(f"Outcome for the mismatched container: status={container_outcome.status!r} detail={container_outcome.detail!r}")
        assert container_outcome.status == "refused", f"FAIL: expected 'refused', got {container_outcome.status!r}"
        assert "mismatch" in container_outcome.detail
        assert _container_exists(mismatched_container), "FAIL: the container was deleted despite the label mismatch"
        print("PASS: the container was NOT deleted -- the database row claimed session "
              f"{mismatched_session_id}, but the live Docker label actually reads {real_owner_id}, "
              "and orphan_sweep.py refused the mismatch instead of trusting the row alone.")
    finally:
        _remove_container_if_present(mismatched_container)
        if mismatched_session_id:
            await _cleanup_row(mismatched_session_id)

    _print_header("ALL CASES PASSED (A, B, C, D)")


if __name__ == "__main__":
    asyncio.run(_main())
