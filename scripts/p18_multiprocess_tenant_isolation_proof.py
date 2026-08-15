"""
P18 — real, separate-OS-process proof of tenant isolation, extending P17's
own single-process proof (scripts/p17_tenant_isolation_proof.py — real app,
real Postgres, real HTTP, but one process) with the properties Phase 7 of
this phase's own instructions specifically ask for and P17 never attempted:

  Case 1 — two genuinely separate OS processes, each authenticated as a
           DIFFERENT tenant, racing (via a real multiprocessing.Barrier,
           not a hopeful sleep) to reject EACH OTHER's capability request
           at the exact same instant — proves tenant A cannot mutate
           tenant B's request (and vice versa) even under real process-
           level concurrency, not just sequential HTTP calls.
  Case 2 — WITHIN one process, N genuinely concurrent asyncio Tasks
           (asyncio.gather over an async ASGI transport, not sequential
           awaits) alternating tenant-A- and tenant-B-authenticated GET
           requests against the SAME running app instance — the actual
           scenario db/tenancy.py's docstring claims a contextvars.
           ContextVar is safe against: a request's own `.set()` must be
           invisible to a concurrent sibling Task's request. Proves no
           tenant's response ever contains the other tenant's data.
  Case 3 — a background reconciliation call
           (capability_reconcile.mark_stalled_executions_unknown) invoked
           from INSIDE an ambient use_tenant(tenant_A) context (simulating
           what would happen if a future caller mistakenly reached it from
           a tenant-scoped code path) — proves the module's own internal
           use_all_tenants() override wins over an outer, narrower ambient
           context, not merely "happens to work" because nothing else was
           set. Directly answers Phase 1's "verify ContextVar tenant state
           cannot leak between concurrent async requests" for the
           background-job direction specifically.

Same standalone-script convention as scripts/p14_multiprocess_capability_
proof.py / scripts/p15_multiprocess_concurrency_proof.py: not
pytest-collected, multiprocessing.get_context("spawn") for genuine process
isolation, the real ados_test database, independently re-verified cleanup.
No external (ServiceNow) side effect anywhere — every decision here is
`reject`, which has zero external effect and shares the identical
authorization gates `approve` does (P16/P17's own established reasoning).

Usage:
    .venv/bin/python scripts/p18_multiprocess_tenant_isolation_proof.py
"""

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://ados:ados@localhost:5432/ados_test"

import asyncio
import multiprocessing as mp
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CTX = mp.get_context("spawn")
RUN_ID = uuid.uuid4().hex[:8]


def _tag(label: str) -> str:
    return f"p18.mp_proof.{RUN_ID}.{label}"


# ---------------------------------------------------------------------
# Worker process
# ---------------------------------------------------------------------

def worker_main(name: str, cmd_queue: "mp.Queue", result_queue: "mp.Queue", barrier=None) -> None:
    asyncio.run(_worker_loop(name, cmd_queue, result_queue, barrier))


async def _worker_loop(name: str, cmd_queue, result_queue, barrier=None) -> None:
    import httpx

    from backend.app.main import app
    from backend.app.rbac import User, Role, create_access_token
    from db.tenancy import use_tenant

    def _headers(user_id: str, tenant_id: str, username: str) -> dict:
        user = User(
            user_id=user_id, username=username, display_name="test",
            role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0, tenant_ids=[tenant_id],
        )
        return {"Authorization": f"Bearer {create_access_token(user)}"}

    while True:
        cmd = await asyncio.get_event_loop().run_in_executor(None, cmd_queue.get)
        op = cmd["op"]
        if op == "exit":
            result_queue.put({"op": "exit", "worker": name, "pid": os.getpid()})
            return
        try:
            if op == "report_pid":
                result_queue.put({"op": op, "worker": name, "pid": os.getpid()})

            elif op == "reject_at_barrier":
                # Case 1: two real OS processes racing on a real barrier
                # (passed at process-spawn time via `Process(args=...)` —
                # a spawn-context synchronization primitive can only be
                # inherited that way, not sent later through a Queue),
                # each authenticated as its OWN tenant, each attempting to
                # reject the OTHER tenant's request AND its own — real
                # simultaneity, not a hopeful sleep.
                headers = _headers(cmd["user_id"], cmd["tenant_id"], cmd["username"])
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    barrier.wait()
                    foreign = await client.post(
                        f"/runtime/capability-requests/{cmd['foreign_request_id']}/reject",
                        headers=headers, json={"reason": "p18 cross-tenant race"},
                    )
                    own = await client.post(
                        f"/runtime/capability-requests/{cmd['own_request_id']}/reject",
                        headers=headers, json={"reason": "p18 own-tenant decision"},
                    )
                result_queue.put({
                    "op": op, "worker": name, "pid": os.getpid(),
                    "foreign_status": foreign.status_code,
                    "own_status": own.status_code, "own_body": own.json() if own.status_code == 200 else own.text,
                })

            elif op == "concurrent_cross_tenant_probe":
                # Case 2: genuinely concurrent asyncio Tasks (asyncio.gather,
                # not sequential awaits), alternating tenant-A and tenant-B
                # credentials against the SAME app instance in the SAME
                # event loop — the exact scenario the ContextVar must get
                # right. n_rounds interleaved GETs per tenant.
                headers_a = _headers(cmd["user_a_id"], cmd["tenant_a_id"], "probe-a")
                headers_b = _headers(cmd["user_b_id"], cmd["tenant_b_id"], "probe-b")

                async def _get_as(client, headers, path):
                    resp = await client.get(path, headers=headers)
                    return resp.status_code, (resp.json() if resp.status_code == 200 else None)

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    n = cmd["n_rounds"]
                    tasks = []
                    for i in range(n):
                        tasks.append(_get_as(client, headers_a, "/runtime/capability-requests"))
                        tasks.append(_get_as(client, headers_b, "/runtime/capability-requests"))
                    results = await asyncio.gather(*tasks)

                a_ids = {cmd["a_request_id"]}
                b_ids = {cmd["b_request_id"]}
                leaks = []
                for i, (status, body) in enumerate(results):
                    is_a_call = (i % 2 == 0)
                    if status != 200 or body is None:
                        leaks.append({"index": i, "reason": f"unexpected status {status}"})
                        continue
                    seen = {r["requestId"] for r in body["requests"]}
                    if is_a_call:
                        if cmd["b_request_id"] in seen:
                            leaks.append({"index": i, "reason": "tenant A's concurrent call saw tenant B's request"})
                        if cmd["a_request_id"] not in seen:
                            leaks.append({"index": i, "reason": "tenant A's concurrent call did NOT see its own request"})
                    else:
                        if cmd["a_request_id"] in seen:
                            leaks.append({"index": i, "reason": "tenant B's concurrent call saw tenant A's request"})
                        if cmd["b_request_id"] not in seen:
                            leaks.append({"index": i, "reason": "tenant B's concurrent call did NOT see its own request"})
                result_queue.put({
                    "op": op, "worker": name, "pid": os.getpid(),
                    "rounds": n, "total_calls": len(results), "leaks": leaks,
                })

            elif op == "background_override_probe":
                # Case 3: call the real reconciliation function from INSIDE
                # an ambient, narrower use_tenant() context — proving its
                # own internal use_all_tenants() (db/tenancy.py) really
                # overrides the caller's ambient context rather than
                # inheriting it.
                from db.engine import async_session_factory
                from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown

                with use_tenant(uuid.UUID(cmd["ambient_tenant_id"])):
                    stalled = await mark_stalled_executions_unknown(
                        async_session_factory, stall_seconds=cmd.get("stall_seconds", 0)
                    )
                seen_ids = {str(s.request_id) for s in stalled}
                result_queue.put({
                    "op": op, "worker": name, "pid": os.getpid(),
                    "saw_ambient_tenant_row": cmd["ambient_tenant_request_id"] in seen_ids,
                    "saw_other_tenant_row": cmd["other_tenant_request_id"] in seen_ids,
                    "count": len(stalled),
                })

            else:
                result_queue.put({"op": op, "worker": name, "ok": False, "error": f"unknown op {op!r}"})
        except Exception as e:  # noqa: BLE001 — report, never crash the worker loop
            result_queue.put({"op": op, "worker": name, "ok": False, "error": f"{type(e).__name__}: {e}", "pid": os.getpid()})


class Worker:
    def __init__(self, name: str, barrier=None):
        self.name = name
        self.cmd_queue: mp.Queue = CTX.Queue()
        self.result_queue: mp.Queue = CTX.Queue()
        self.process = CTX.Process(
            target=worker_main, args=(name, self.cmd_queue, self.result_queue, barrier), daemon=True
        )
        self.process.start()

    def send(self, op: str, **kwargs) -> dict:
        self.cmd_queue.put({"op": op, **kwargs})
        return self.result_queue.get(timeout=60)

    def send_nowait(self, op: str, **kwargs) -> None:
        self.cmd_queue.put({"op": op, **kwargs})

    def recv(self) -> dict:
        return self.result_queue.get(timeout=60)

    def stop(self) -> None:
        if not self.process.is_alive():
            return
        self.cmd_queue.put({"op": "exit"})
        self.process.join(timeout=10)
        if self.process.is_alive():
            self.process.terminate()


# ---------------------------------------------------------------------
# Main / driver process
# ---------------------------------------------------------------------

async def _seed():
    from sqlalchemy import text
    from db.engine import async_session_factory
    from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
    from db.models.tenant import DEFAULT_TENANT_ID, TenantMembershipRow, TenantRow
    from db.tenancy import use_all_tenants
    from orchestrate.runtime.prime import token_expiry

    tenant_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    async with async_session_factory() as db:
        db.add(TenantRow(tenant_id=tenant_b_id, name=_tag("tenant-b"), slug=f"p18-{RUN_ID}"))
        db.add(TenantMembershipRow(tenant_id=tenant_b_id, user_id=user_b_id))
        await db.commit()

    ids = {}
    with use_all_tenants():
        async with async_session_factory() as db:
            for label, tenant_id in (("a", DEFAULT_TENANT_ID), ("b", tenant_b_id)):
                mission = MissionRow(
                    title=_tag(f"mission-{label}"), objective="o", domain="it",
                    allowed_capabilities=["NotifyITHelpdesk"], status="running", tenant_id=tenant_id,
                )
                db.add(mission)
                await db.flush()
                sess = RuntimeSessionRow(
                    mission_id=mission.mission_id, tenant_id=tenant_id, state="running",
                    token_hash=f"p18-unused-{label}", token_expires_at=token_expiry(1800.0),
                )
                db.add(sess)
                await db.flush()
                req = CapabilityRequestRow(
                    session_id=sess.session_id, mission_id=mission.mission_id, tenant_id=tenant_id,
                    capability="NotifyITHelpdesk", arguments={"summary": _tag(f"req-{label}")},
                    policy_tier=1, status="pending_approval",
                    idempotency_key=_tag(f"idem-{label}"),
                )
                db.add(req)
                await db.flush()
                ids[label] = {"mission_id": str(mission.mission_id), "session_id": str(sess.session_id), "request_id": str(req.request_id)}
            await db.commit()

    return tenant_b_id, user_a_id, user_b_id, ids


async def _seed_stalled(tenant_a_id, tenant_b_id):
    """A second pair of requests, already 'executing' and backdated past the
    stall bound, for Case 3's background-reconciliation probe."""
    from datetime import datetime, timedelta, timezone

    from db.engine import async_session_factory
    from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
    from db.tenancy import use_all_tenants
    from orchestrate.runtime.capability_execution import STATUS_EXECUTING
    from orchestrate.runtime.prime import token_expiry

    ids = {}
    with use_all_tenants():
        async with async_session_factory() as db:
            for label, tenant_id in (("a2", tenant_a_id), ("b2", tenant_b_id)):
                mission = MissionRow(
                    title=_tag(f"mission-{label}"), objective="o", domain="it",
                    allowed_capabilities=["NotifyITHelpdesk"], status="running", tenant_id=tenant_id,
                )
                db.add(mission)
                await db.flush()
                sess = RuntimeSessionRow(
                    mission_id=mission.mission_id, tenant_id=tenant_id, state="running",
                    token_hash=f"p18-unused-{label}", token_expires_at=token_expiry(1800.0),
                )
                db.add(sess)
                await db.flush()
                req = CapabilityRequestRow(
                    session_id=sess.session_id, mission_id=mission.mission_id, tenant_id=tenant_id,
                    capability="NotifyITHelpdesk", arguments={"summary": _tag(f"stalled-{label}")},
                    policy_tier=1, status=STATUS_EXECUTING,
                    idempotency_key=_tag(f"idem-stalled-{label}"),
                    updated_at=datetime.now(timezone.utc) - timedelta(seconds=120),
                )
                db.add(req)
                await db.flush()
                ids[label] = str(req.request_id)
            await db.commit()
    return ids


async def _cleanup():
    from sqlalchemy import text
    from db.engine import async_session_factory

    async with async_session_factory() as db:
        await db.execute(text("DELETE FROM capability_requests WHERE idempotency_key LIKE :p"), {"p": f"p18.mp_proof.{RUN_ID}.%"})
        await db.execute(text("DELETE FROM runtime_sessions WHERE token_hash LIKE :p"), {"p": f"p18-unused-%"})
        await db.execute(text("DELETE FROM missions WHERE title LIKE :p"), {"p": f"p18.mp_proof.{RUN_ID}.%"})
        await db.execute(text("DELETE FROM tenant_memberships WHERE tenant_id IN (SELECT tenant_id FROM tenants WHERE slug = :s)"), {"s": f"p18-{RUN_ID}"})
        await db.execute(text("DELETE FROM tenants WHERE slug = :s"), {"s": f"p18-{RUN_ID}"})
        await db.commit()


async def _independent_verify() -> bool:
    from sqlalchemy import text
    from db.engine import async_session_factory

    async with async_session_factory() as db:
        remaining_missions = (
            await db.execute(text("SELECT count(*) FROM missions WHERE title LIKE :p"), {"p": f"p18.mp_proof.{RUN_ID}.%"})
        ).scalar_one()
        remaining_tenant = (
            await db.execute(text("SELECT count(*) FROM tenants WHERE slug = :s"), {"s": f"p18-{RUN_ID}"})
        ).scalar_one()
    ok = remaining_missions == 0 and remaining_tenant == 0
    print(f"      independent post-cleanup verification: missions={remaining_missions} tenants={remaining_tenant} -> {'PASS' if ok else 'FAIL'}")
    return ok


async def main() -> int:
    from db.models.tenant import DEFAULT_TENANT_ID

    print("=" * 78)
    print("P18 MULTI-PROCESS TENANT ISOLATION PROOF -- real separate OS processes,")
    print("real Postgres, real HTTP, no ServiceNow")
    print("=" * 78)

    tenant_b_id, user_a_id, user_b_id, ids = await _seed()
    ok = True

    # --- Case 2 runs FIRST -------------------------------------------------
    # (both requests are still `pending_approval` here — the default list
    # filter GET /runtime/capability-requests uses. Case 1, below, decides
    # both requests, which would make them fall out of that default view;
    # running Case 2 first avoids conflating "already decided elsewhere" —
    # not a leak — with an actual cross-tenant leak.)
    print("\n" + "=" * 70)
    print("CASE 2 -- WITHIN one process, genuinely concurrent asyncio Tasks")
    print("(asyncio.gather) alternating tenant-A/tenant-B credentials against")
    print("the same running app instance and event loop")
    print("=" * 70)
    w_c = Worker("concurrent-probe")
    r_c = w_c.send(
        "concurrent_cross_tenant_probe",
        user_a_id=str(user_a_id), tenant_a_id=str(DEFAULT_TENANT_ID),
        user_b_id=str(user_b_id), tenant_b_id=str(tenant_b_id),
        a_request_id=ids["a"]["request_id"], b_request_id=ids["b"]["request_id"],
        n_rounds=15,
    )
    print(f"  {r_c['total_calls']} genuinely concurrent HTTP calls fired (asyncio.gather, {r_c['rounds']} rounds x 2 tenants)")
    case2_ok = not r_c["leaks"]
    print(f"  [{'PASS' if case2_ok else 'FAIL'}] zero cross-tenant leaks across {r_c['total_calls']} concurrent calls: {len(r_c['leaks'])} leak(s)")
    if r_c["leaks"]:
        for leak in r_c["leaks"]:
            print(f"      LEAK: {leak}")
    ok = ok and case2_ok
    w_c.stop()

    # --- Case 1 -----------------------------------------------------------
    print("\n" + "=" * 70)
    print("CASE 1 -- two real OS processes, different tenants, racing on a real")
    print("Barrier to reject EACH OTHER's request at the exact same instant")
    print("=" * 70)
    barrier = CTX.Barrier(2)
    w_a = Worker("tenant-a", barrier=barrier)
    w_b = Worker("tenant-b", barrier=barrier)
    w_a.send_nowait(
        "reject_at_barrier",
        user_id=str(user_a_id), tenant_id=str(DEFAULT_TENANT_ID), username="p18-a",
        foreign_request_id=ids["b"]["request_id"], own_request_id=ids["a"]["request_id"],
    )
    w_b.send_nowait(
        "reject_at_barrier",
        user_id=str(user_b_id), tenant_id=str(tenant_b_id), username="p18-b",
        foreign_request_id=ids["a"]["request_id"], own_request_id=ids["b"]["request_id"],
    )
    r_a = w_a.recv()
    r_b = w_b.recv()
    print(f"  worker-a (pid={r_a.get('pid')}): foreign_status={r_a['foreign_status']} own_status={r_a['own_status']}")
    print(f"  worker-b (pid={r_b.get('pid')}): foreign_status={r_b['foreign_status']} own_status={r_b['own_status']}")
    assert r_a.get("pid") != r_b.get("pid"), "workers must be genuinely separate OS processes"
    case1_ok = (
        r_a["foreign_status"] == 404 and r_b["foreign_status"] == 404
        and r_a["own_status"] == 200 and r_b["own_status"] == 200
    )
    print(f"  [{'PASS' if case1_ok else 'FAIL'}] tenant A refused on tenant B's request (404): {r_a['foreign_status'] == 404}")
    print(f"  [{'PASS' if case1_ok else 'FAIL'}] tenant B refused on tenant A's request (404): {r_b['foreign_status'] == 404}")
    print(f"  [{'PASS' if case1_ok else 'FAIL'}] each tenant DID successfully decide its OWN request (200): {r_a['own_status'] == 200 and r_b['own_status'] == 200}")
    ok = ok and case1_ok
    w_a.stop()
    w_b.stop()

    # --- Case 3 -------------------------------------------------------------
    print("\n" + "=" * 70)
    print("CASE 3 -- background reconciliation called from INSIDE an ambient,")
    print("narrower use_tenant() context -- proves its own internal")
    print("use_all_tenants() overrides the caller's context, not inherits it")
    print("=" * 70)
    stalled_ids = await _seed_stalled(DEFAULT_TENANT_ID, tenant_b_id)
    w_d = Worker("background-probe")
    r_d = w_d.send(
        "background_override_probe",
        ambient_tenant_id=str(DEFAULT_TENANT_ID),
        ambient_tenant_request_id=stalled_ids["a2"],
        other_tenant_request_id=stalled_ids["b2"],
        stall_seconds=0,
    )
    print(f"  reconciliation ran inside `with use_tenant(DEFAULT_TENANT_ID):`, found {r_d['count']} stalled row(s)")
    case3_ok = r_d["saw_ambient_tenant_row"] and r_d["saw_other_tenant_row"]
    print(f"  [{'PASS' if r_d['saw_ambient_tenant_row'] else 'FAIL'}] saw the ambient (tenant A) tenant's own stalled row: {r_d['saw_ambient_tenant_row']}")
    print(f"  [{'PASS' if r_d['saw_other_tenant_row'] else 'FAIL'}] ALSO saw tenant B's stalled row (proves the ambient context was overridden, not inherited): {r_d['saw_other_tenant_row']}")
    ok = ok and case3_ok
    w_d.stop()

    # --- cleanup --------------------------------------------------------------
    print("\n" + "=" * 70)
    print("CLEANUP")
    print("=" * 70)
    await _cleanup()
    cleanup_ok = await _independent_verify()
    ok = ok and cleanup_ok

    print("\n" + "=" * 78)
    print("RESULT:", "PASS -- all cases passed across real, separate OS processes." if ok else "FAIL -- see above.")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
