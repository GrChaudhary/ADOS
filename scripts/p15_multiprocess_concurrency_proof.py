"""
P15 — real, separate-OS-process proof of the concurrency/atomicity
invariants defined in docs/prime-agent-integration/26-p15-concurrency-
atomicity-review.md, for the races P14's own script did NOT cover (that
script proves capability disable/enable propagation exhaustively already —
re-run here unmodified as part of this phase's evidence, not reimplemented).

Covers, each across genuinely separate OS processes against real Postgres:

  Case 1 — double approval race (Invariant C): two processes racing to
           decide the SAME parked capability_requests row.
  Case 2 — double execution / idempotency race (Invariant D): two processes
           racing to submit the SAME canonical request for the first time.
  Case 3 — reconciliation vs. a genuinely-still-executing row (Invariant E,
           the P15 fix in backend/app/mcp_gateway.py), AND a REAL crash
           boundary: one worker process is SIGKILLed mid-external-call (not
           a simulated exception) and reconciliation is proven to recover
           the row correctly.
  Case 4 — admission-control race (Invariant F): N processes racing for a
           global ceiling far smaller than N.
  Case 5 — token-expiry race (Invariant G): concurrent attempts against a
           NULL-expiry and an already-past-expiry session, from multiple
           processes, alongside a control session to rule out a blanket
           false-positive.

Same standalone-script convention as scripts/p14_multiprocess_capability_
proof.py (not pytest-collected); same multiprocessing.get_context("spawn")
mechanism for genuine process isolation; same ados_test database with
independently re-verified cleanup before exit.

Usage:
    .venv/bin/python scripts/p15_multiprocess_concurrency_proof.py
"""

import os

os.environ["DATABASE_URL"] = "postgresql+asyncpg://ados:ados@localhost:5432/ados_test"

import asyncio
import multiprocessing as mp
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CTX = mp.get_context("spawn")
RUN_ID = uuid.uuid4().hex[:8]


def _tag(label: str) -> str:
    return f"p15.mp_proof.{RUN_ID}.{label}"


# ---------------------------------------------------------------------
# Worker process
# ---------------------------------------------------------------------


def worker_main(name: str, cmd_queue: "mp.Queue", result_queue: "mp.Queue") -> None:
    asyncio.run(_worker_loop(name, cmd_queue, result_queue))


async def _worker_loop(name: str, cmd_queue, result_queue) -> None:
    from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse, GovernanceInfo, PolicyTier
    from db.engine import async_session_factory
    from db.tenancy import use_all_tenants
    from fastapi import HTTPException
    from sqlalchemy import select

    from backend.app import mcp_gateway
    from backend.app.mcp_gateway import request_capability
    from backend.app.routers.runtime_approvals import _load_pending_or_404
    from db.models.mission import CapabilityRequestRow
    from integrations.admission_control import AdmissionControl
    from integrations.capability_manifest import CapabilityManifestRegistry
    from integrations.connectors.base import Connector
    from integrations.hub import IntegrationHub, default_hub
    from integrations.rate_limiter import RateLimiter
    from orchestrate.runtime.capability_execution import STATUS_EXECUTING

    # Real global wiring, matching backend/app/main.py's own lifespan
    # exactly (manifests / admission_control / rate_limiter all wired with
    # the real session_factory) -- this worker's default_hub() is left
    # untouched (never monkeypatched here), so mcp_gateway._hub_for_
    # execution() will genuinely select this hub via _active_hub, the
    # documented real-app path.
    hub = default_hub(
        manifests=CapabilityManifestRegistry(session_factory=async_session_factory),
        admission_control=AdmissionControl(
            max_concurrent_capability_executions=999, max_concurrent_missions=999,
            session_factory=async_session_factory,
        ),
        rate_limiter=RateLimiter(session_factory=async_session_factory),
    )
    mcp_gateway._active_hub = hub

    current_token = {"value": None}
    mcp_gateway.get_http_headers = lambda: {"authorization": f"Bearer {current_token['value']}"}

    background_tasks: dict = {}

    class _SlowConnector(Connector):
        """Blocks on an asyncio.Event -- stands in for a real, slow but
        genuinely still-alive external call, never released until this
        worker is told to (or is killed outright, for the crash case)."""

        def __init__(self, capability: Capability):
            self.name = "slow-connector"
            self.capabilities = {capability}
            self.gate = asyncio.Event()

        async def execute(self, call: CapabilityCall) -> CapabilityResponse:
            await self.gate.wait()
            return CapabilityResponse(request_id=call.request_id, status=CallStatus.SUCCEEDED, connector=self.name)

    def _call(capability: "Capability", incident_id: str) -> "CapabilityCall":
        return CapabilityCall(
            capability=capability, incident_id=incident_id,
            requested_by=f"scripts/p15_multiprocess_concurrency_proof:{name}",
            input={}, governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
        )

    while True:
        # A plain blocking cmd_queue.get() here would starve this process's
        # asyncio event loop -- fatal for "begin_slow_request_capability"
        # below, whose whole point is a background task that must keep
        # making progress (through its own real awaits) while this loop
        # waits for the driver's NEXT command. run_in_executor keeps the
        # blocking multiprocessing.Queue read off the event loop thread.
        cmd = await asyncio.get_event_loop().run_in_executor(None, cmd_queue.get)
        op = cmd["op"]
        if op == "exit":
            result_queue.put({"op": "exit", "worker": name, "pid": os.getpid()})
            return
        try:
            if op == "request_capability":
                current_token["value"] = cmd["token"]
                t0 = time.monotonic()
                result = await request_capability.fn(cmd["capability"], cmd.get("arguments") or {})
                t1 = time.monotonic()
                result_queue.put({"op": op, "worker": name, "pid": os.getpid(), "result": result, "t_start": t0, "t_end": t1})

            elif op == "attempt_approve_decision":
                # The exact mechanism backend/app/routers/runtime_approvals.
                # py::approve_capability_request depends on for Invariant C
                # -- SELECT ... FOR UPDATE plus a conditional status check --
                # exercised directly, without the FastAPI/JWT dependency
                # layer, which carries no concurrency semantics of its own.
                request_id = cmd["request_id"]  # _load_pending_or_404 does its own uuid.UUID(str) parse
                try:
                    # P17 -- this call bypasses the FastAPI dependency layer
                    # by design (see comment above: it isolates the
                    # concurrency primitive from auth concerns). Tenant
                    # scoping is now also resolved through that same
                    # dependency layer (get_tenant_context), so bypassing it
                    # here would fail closed on a row that genuinely exists
                    # -- not a concurrency finding, just an artifact of
                    # skipping the layer that would normally set it.
                    # use_all_tenants() preserves the original intent
                    # exactly: test the DB-level lock/status-check primitive,
                    # with every non-concurrency concern (auth, tenancy)
                    # deliberately out of the way.
                    with use_all_tenants():
                        async with async_session_factory() as session:
                            async with session.begin():
                                row = await _load_pending_or_404(session, request_id)
                                row.status = STATUS_EXECUTING
                                row.decided_by = f"worker:{name}"
                    result_queue.put({"op": op, "worker": name, "pid": os.getpid(), "ok": True})
                except HTTPException as e:
                    result_queue.put({"op": op, "worker": name, "pid": os.getpid(), "ok": False, "status_code": e.status_code, "detail": e.detail})

            elif op == "install_slow_connector":
                capability = Capability(cmd["capability"])
                slow = _SlowConnector(capability)
                background_tasks["_slow_connector"] = slow
                monkey_registry = hub.registry
                orig_connectors_for = monkey_registry.connectors_for

                def _patched(cap, _orig=orig_connectors_for, _slow=slow, _cap=capability):
                    return [_slow] if cap == _cap else _orig(cap)

                monkey_registry.connectors_for = _patched
                result_queue.put({"op": op, "worker": name, "ok": True})

            elif op == "begin_slow_request_capability":
                current_token["value"] = cmd["token"]

                async def _run():
                    return await request_capability.fn(cmd["capability"], cmd.get("arguments") or {})

                task = asyncio.create_task(_run())
                background_tasks["task"] = task
                await asyncio.sleep(0)  # let it actually start
                result_queue.put({"op": op, "worker": name, "pid": os.getpid(), "ok": True})

            elif op == "release_slow_connector_and_await":
                background_tasks["_slow_connector"].gate.set()
                result = await background_tasks["task"]
                result_queue.put({"op": op, "worker": name, "result": result})

            elif op == "report_pid":
                result_queue.put({"op": op, "worker": name, "pid": os.getpid()})

            elif op == "mark_stalled":
                from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown
                stalled = await mark_stalled_executions_unknown(async_session_factory, stall_seconds=cmd.get("stall_seconds", 0))
                result_queue.put({"op": op, "worker": name, "count": len(stalled), "ids": [str(s.request_id) for s in stalled]})

            elif op == "hub_invoke_admission_probe":
                capability = Capability(cmd["capability"])
                t0 = time.monotonic()
                response = await hub.invoke(_call(capability, cmd.get("incident_id", "p15-admission")))
                t1 = time.monotonic()
                result_queue.put({
                    "op": op, "worker": name, "pid": os.getpid(),
                    "status": response.status.value, "error": response.error,
                    "t_start": t0, "t_end": t1,
                })

            else:
                result_queue.put({"op": op, "worker": name, "ok": False, "error": f"unknown op {op!r}"})
        except Exception as e:  # noqa: BLE001 — report, never crash the worker loop
            result_queue.put({"op": op, "worker": name, "ok": False, "error": f"{type(e).__name__}: {e}", "pid": os.getpid()})


class Worker:
    def __init__(self, name: str):
        self.name = name
        self.cmd_queue: mp.Queue = CTX.Queue()
        self.result_queue: mp.Queue = CTX.Queue()
        self.process = CTX.Process(target=worker_main, args=(name, self.cmd_queue, self.result_queue), daemon=True)
        self.process.start()

    def send(self, op: str, **kwargs) -> dict:
        self.cmd_queue.put({"op": op, **kwargs})
        return self.result_queue.get(timeout=30)

    def send_nowait(self, op: str, **kwargs) -> None:
        self.cmd_queue.put({"op": op, **kwargs})

    def recv(self) -> dict:
        return self.result_queue.get(timeout=30)

    def kill(self) -> None:
        """A REAL crash -- SIGKILL, not a simulated exception. No `finally`
        block anywhere in this process gets to run."""
        os.kill(self.process.pid, signal.SIGKILL)
        self.process.join(timeout=10)

    def stop(self) -> None:
        if not self.process.is_alive():
            return
        self.cmd_queue.put({"op": "exit"})
        self.process.join(timeout=10)
        if self.process.is_alive():
            self.process.terminate()


# ---------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{label} — {detail}")


# ---------------------------------------------------------------------
# Direct (driver-side) DB helpers
# ---------------------------------------------------------------------


async def _make_mission_and_session(capability: str, *, expires_delta: "timedelta | None") -> tuple[str, str, str]:
    from db.engine import async_session_factory
    from db.models.mission import MissionRow, RuntimeSessionRow
    from backend.app.mcp_gateway import hash_token

    async with async_session_factory() as db:
        mission = MissionRow(
            title=_tag("mission"), objective="o", domain="it",
            allowed_capabilities=[capability], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        expires_at = (datetime.now(timezone.utc) + expires_delta) if expires_delta is not None else None
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            token_expires_at=expires_at,
        )
        db.add(sess)
        await db.commit()
        return str(mission.mission_id), str(sess.session_id), token


async def _park_pending_approval(capability: str, *, tier: int = 1) -> tuple[str, str]:
    """Directly writes a `pending_approval` capability_requests row —
    equivalent to what request_capability's own park branch does for a
    Tier 1/2 capability, without needing a real Tier-1 grant/governance
    path just to set up this test."""
    from db.engine import async_session_factory
    from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
    from backend.app.mcp_gateway import hash_token

    async with async_session_factory() as db:
        mission = MissionRow(title=_tag("approval-mission"), objective="o", domain="it", allowed_capabilities=[capability], status="running")
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="waiting_approval", token_hash=hash_token(token),
            token_expires_at=datetime.now(timezone.utc) + timedelta(seconds=1800),
        )
        db.add(sess)
        await db.flush()
        row = CapabilityRequestRow(
            session_id=sess.session_id, mission_id=mission.mission_id, capability=capability,
            arguments={}, status="pending_approval", policy_tier=tier, idempotency_key=_tag(f"approve-{uuid.uuid4().hex}"),
        )
        db.add(row)
        await db.commit()
        return str(row.request_id), str(mission.mission_id)


async def _row_status(request_id: str) -> "CapabilityRequestRow | None":
    from db.engine import async_session_factory
    from db.models.mission import CapabilityRequestRow
    from db.tenancy import use_all_tenants

    # P17 -- a plain verification read, same reasoning as the worker's
    # direct _load_pending_or_404 call above: this script's own driver
    # process never resolves a tenant context (it isn't testing tenancy),
    # so a real query here needs the same explicit opt-out.
    with use_all_tenants():
        async with async_session_factory() as db:
            return await db.get(CapabilityRequestRow, uuid.UUID(request_id))


async def _wait_for_row_status(request_id: str, expected: str, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = await _row_status(request_id)
        if row is not None and row.status == expected:
            return True
        await asyncio.sleep(0.02)
    return False


# ---------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------


def case_1_double_approval_race(worker_a: Worker, worker_b: Worker) -> None:
    print("\n=== Case 1 — double approval race (Invariant C) ===")
    request_id, _ = asyncio.run(_park_pending_approval("NotifyITHelpdesk"))

    worker_a.send_nowait("attempt_approve_decision", request_id=request_id)
    worker_b.send_nowait("attempt_approve_decision", request_id=request_id)
    ra = worker_a.recv()
    rb = worker_b.recv()

    winners = [r for r in (ra, rb) if r["ok"]]
    losers = [r for r in (ra, rb) if not r["ok"]]
    check("exactly one worker wins the decision lock", len(winners) == 1, f"a={ra} b={rb}")
    check("the loser is refused with 409 (already decided), not a silent second success", len(losers) == 1 and losers[0]["status_code"] == 409, str(losers))

    row = asyncio.run(_row_status(request_id))
    check("the row shows exactly the one decision made, durably", row.status == "executing" and row.decided_by is not None, f"status={row.status} decided_by={row.decided_by}")


def case_2_double_execution_idempotency_race(worker_a: Worker, worker_b: Worker) -> None:
    print("\n=== Case 2 — double execution / idempotency race (Invariant D) ===")
    _, _, token = asyncio.run(_make_mission_and_session("NotifyOperator", expires_delta=timedelta(seconds=1800)))

    worker_a.send_nowait("request_capability", token=token, capability="NotifyOperator", arguments={"message": _tag("race")})
    worker_b.send_nowait("request_capability", token=token, capability="NotifyOperator", arguments={"message": _tag("race")})
    ra = worker_a.recv()["result"]
    rb = worker_b.recv()["result"]

    check("both callers resolve to the SAME request_id", ra["request_id"] == rb["request_id"], f"a={ra['request_id']} b={rb['request_id']}")
    check("exactly one of the two calls is the original, the other a replay", ra.get("replayed") != rb.get("replayed"), f"a.replayed={ra.get('replayed')} b.replayed={rb.get('replayed')}")

    async def _rows_for_request():
        from sqlalchemy import select
        from db.engine import async_session_factory
        from db.models.mission import CapabilityRequestRow
        from db.tenancy import use_all_tenants
        with use_all_tenants():
            async with async_session_factory() as db:
                return (await db.execute(select(CapabilityRequestRow).where(CapabilityRequestRow.request_id == uuid.UUID(ra["request_id"])))).scalars().all()

    rows = asyncio.run(_rows_for_request())
    check("exactly one durable row exists for this canonical request, not two", len(rows) == 1, f"{len(rows)} rows")


async def _find_request_id_for_session(session_id: str):
    from sqlalchemy import select
    from db.engine import async_session_factory
    from db.models.mission import CapabilityRequestRow
    from db.tenancy import use_all_tenants
    with use_all_tenants():
        async with async_session_factory() as db:
            rows = (
                await db.execute(select(CapabilityRequestRow).where(CapabilityRequestRow.session_id == uuid.UUID(session_id)))
            ).scalars().all()
    return str(rows[0].request_id) if rows else None


def case_3_reconciliation_and_crash_boundary(worker_slow: Worker, worker_reconciler: Worker) -> None:
    print("\n=== Case 3a — reconciliation vs. a genuinely-still-executing row (Invariant E, the P15 fix) ===")
    _, session_id_a, token = asyncio.run(_make_mission_and_session("NotifyITHelpdesk", expires_delta=timedelta(seconds=1800)))
    worker_slow.send("install_slow_connector", capability="NotifyITHelpdesk")
    r = worker_slow.send("begin_slow_request_capability", token=token, capability="NotifyITHelpdesk", arguments={"summary": _tag("slow")})
    check("the slow call started", r["ok"])

    request_id = None
    row = None
    for _ in range(500):
        request_id = asyncio.run(_find_request_id_for_session(session_id_a))
        if request_id:
            row = asyncio.run(_row_status(request_id))
            if row is not None and row.status == "executing":
                break
        time.sleep(0.02)
    check("the row reached the durable executing checkpoint while the call is genuinely still in flight", request_id is not None and row is not None and row.status == "executing")

    reconcile = worker_reconciler.send("mark_stalled", stall_seconds=0)
    check("reconciliation (a DIFFERENT process) marks the row outcome_unknown while worker_slow is still alive and working", request_id in reconcile["ids"], reconcile)

    row = asyncio.run(_row_status(request_id))
    reconciled_reason = row.reason
    check("row durably reads outcome_unknown after reconciliation, before the slow call ever returns", row.status == "outcome_unknown")

    finish = worker_slow.send("release_slow_connector_and_await")
    check("the late completion reports outcome_unknown (reconciliation's decision), not executed", finish["result"]["status"] == "outcome_unknown", finish["result"])

    row = asyncio.run(_row_status(request_id))
    check(
        "the late completion did NOT overwrite reconciliation's decision or its reason",
        row.status == "outcome_unknown" and row.reason == reconciled_reason,
        f"status={row.status} reason={row.reason!r} expected_reason={reconciled_reason!r}",
    )
    check("the late completion did not claim to have decided this row", row.decided_by != "policy:autonomous", f"decided_by={row.decided_by}")

    print("\n=== Case 3b — real crash boundary: SIGKILL mid-external-call (Invariant E / H) ===")
    _, session_id_b, token2 = asyncio.run(_make_mission_and_session("NotifyITHelpdesk", expires_delta=timedelta(seconds=1800)))
    worker_crash = Worker("crash")
    try:
        worker_crash.send("install_slow_connector", capability="NotifyITHelpdesk")
        r2 = worker_crash.send("begin_slow_request_capability", token=token2, capability="NotifyITHelpdesk", arguments={"summary": _tag("crash")})
        check("the second slow call started (about to be killed)", r2["ok"])

        request_id2 = None
        row2 = None
        for _ in range(500):
            request_id2 = asyncio.run(_find_request_id_for_session(session_id_b))
            if request_id2:
                row2 = asyncio.run(_row_status(request_id2))
                if row2 is not None and row2.status == "executing":
                    break
            time.sleep(0.02)
        check("the row reached the durable executing checkpoint before the kill", request_id2 is not None and row2 is not None and row2.status == "executing")

        worker_crash.kill()
        check("the worker process is genuinely dead (no finally, no teardown ran)", not worker_crash.process.is_alive())

        reconcile2 = worker_reconciler.send("mark_stalled", stall_seconds=0)
        check("reconciliation recovers the row abandoned by the killed process", request_id2 in reconcile2["ids"], reconcile2)

        row2 = asyncio.run(_row_status(request_id2))
        check("the row durably reads outcome_unknown after a real process kill, never silently re-executable", row2.status == "outcome_unknown")
    finally:
        worker_crash.stop()  # no-op if already dead; harmless either way


def _admission_probe_worker_main(name, cmd_queue, result_queue, limit) -> None:
    asyncio.run(_admission_probe_loop(name, cmd_queue, result_queue, limit))


async def _admission_probe_loop(name, cmd_queue, result_queue, limit) -> None:
    from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse, GovernanceInfo, PolicyTier
    from db.engine import async_session_factory
    from integrations.admission_control import AdmissionControl
    from integrations.connectors.base import Connector
    from integrations.hub import IntegrationHub

    class _AdmissionProbeSpy(Connector):
        """Holds its admission slot open for a visible wall-clock window
        instead of returning instantly. Without this, each spawned
        process's own import time (re-importing the full app stack from
        scratch, per multiprocessing "spawn") dominates: acquire+release
        for one process completes before the next process even finishes
        importing, so the processes never genuinely overlap and the test
        would prove nothing about the real limit."""

        def __init__(self):
            self.name = "spy"
            self.capabilities = {Capability.NOTIFY_OPERATOR}

        async def execute(self, call):
            await asyncio.sleep(1.0)
            return CapabilityResponse(request_id=call.request_id, status=CallStatus.SUCCEEDED, connector=self.name)

    hub = IntegrationHub(admission_control=AdmissionControl(max_concurrent_capability_executions=limit, max_concurrent_missions=limit, session_factory=async_session_factory))
    hub.registry.register(_AdmissionProbeSpy())
    cmd_queue.get()  # driver releases all N processes together, see case_4's own comment
    response = await hub.invoke(CapabilityCall(
        capability=Capability.NOTIFY_OPERATOR, incident_id=_tag("admission-tight"),
        requested_by=f"probe:{name}", input={}, governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    ))
    result_queue.put({"worker": name, "status": response.status.value, "error": response.error})


def case_4_admission_race_tight_limit(limit: int = 3, concurrency: int = 10) -> None:
    """The real proof: N separate OS processes, each with its OWN
    AdmissionControl bound to the SAME real Postgres table, racing for a
    global ceiling far smaller than N. This is what test_admission_control_
    global.py's asyncio.gather version cannot prove -- genuine process
    isolation, not N coroutines sharing one Python process's memory."""
    print(f"\n=== Case 4 — admission race at the real configured limit: {concurrency} real processes, limit={limit} ===")

    procs = []
    for i in range(concurrency):
        cq, rq = CTX.Queue(), CTX.Queue()
        p = CTX.Process(target=_admission_probe_worker_main, args=(f"p{i}", cq, rq, limit), daemon=True)
        p.start()
        procs.append((p, cq, rq))

    for _, cq, _ in procs:
        cq.put({"op": "go"})
    results = [rq.get(timeout=30) for _, _, rq in procs]
    for p, _, _ in procs:
        p.join(timeout=10)

    admitted = [r for r in results if r["status"] == "succeeded"]
    refused = [r for r in results if r["status"] == "failed"]
    print(f"  {len(admitted)} admitted, {len(refused)} refused across {concurrency} real, separate OS processes (limit={limit})")
    check(f"admitted count equals the configured limit exactly ({limit}), not merely 'close to it'", len(admitted) == limit, f"got {len(admitted)}")
    check("refused count makes up the rest", len(refused) == concurrency - limit, f"got {len(refused)}")


def case_5_token_expiry_race(worker_a: Worker, worker_b: Worker, worker_c: Worker) -> None:
    print("\n=== Case 5 — token-expiry race (Invariant G) ===")
    _, _, token_null = asyncio.run(_make_mission_and_session("NotifyOperator", expires_delta=None))
    _, _, token_past = asyncio.run(_make_mission_and_session("NotifyOperator", expires_delta=timedelta(seconds=-10)))
    _, _, token_valid = asyncio.run(_make_mission_and_session("NotifyOperator", expires_delta=timedelta(seconds=1800)))

    worker_a.send_nowait("request_capability", token=token_null, capability="NotifyOperator", arguments={"message": _tag("null-a")})
    worker_b.send_nowait("request_capability", token=token_null, capability="NotifyOperator", arguments={"message": _tag("null-b")})
    worker_c.send_nowait("request_capability", token=token_past, capability="NotifyOperator", arguments={"message": _tag("past-c")})
    ra, rb, rc = worker_a.recv()["result"], worker_b.recv()["result"], worker_c.recv()["result"]

    check("NULL-expiry session refused from worker A", ra["status"] == "denied", ra)
    check("NULL-expiry session refused from worker B, concurrently, from a DIFFERENT process", rb["status"] == "denied", rb)
    check("already-past-expiry session refused from worker C", rc["status"] == "denied", rc)

    # Control: a genuinely valid session, fired concurrently with a fresh
    # round against the same two bad sessions, must NOT be caught up in a
    # blanket refusal.
    worker_a.send_nowait("request_capability", token=token_valid, capability="NotifyOperator", arguments={"message": _tag("valid-a")})
    worker_b.send_nowait("request_capability", token=token_null, capability="NotifyOperator", arguments={"message": _tag("null-b2")})
    valid_result = worker_a.recv()["result"]
    null_result2 = worker_b.recv()["result"]
    check("a genuinely valid session succeeds concurrently with a refused one, from separate processes", valid_result["status"] not in ("denied",), valid_result)
    check("the NULL-expiry session is STILL refused on a second, concurrent attempt", null_result2["status"] == "denied", null_result2)


# ---------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------


async def _cleanup_and_verify() -> None:
    from sqlalchemy import text
    from db.engine import async_session_factory

    title_prefix = f"{_tag('mission')}%"
    approval_title_prefix = f"{_tag('approval-mission')}%"
    async with async_session_factory() as session:
        mission_ids = (
            await session.execute(
                text("SELECT mission_id FROM missions WHERE title LIKE :p1 OR title LIKE :p2"),
                {"p1": title_prefix, "p2": approval_title_prefix},
            )
        ).scalars().all()
        if mission_ids:
            await session.execute(text("DELETE FROM capability_requests WHERE mission_id = ANY(:ids)"), {"ids": mission_ids})
            await session.execute(text("DELETE FROM runtime_sessions WHERE mission_id = ANY(:ids)"), {"ids": mission_ids})
            await session.execute(text("DELETE FROM missions WHERE mission_id = ANY(:ids)"), {"ids": mission_ids})
        await session.commit()

    async with async_session_factory() as session:
        remaining_missions = (
            await session.execute(
                text("SELECT count(*) FROM missions WHERE title LIKE :p1 OR title LIKE :p2"),
                {"p1": title_prefix, "p2": approval_title_prefix},
            )
        ).scalar_one()
        remaining_sessions = (await session.execute(text("SELECT count(*) FROM runtime_sessions rs WHERE NOT EXISTS (SELECT 1 FROM missions m WHERE m.mission_id = rs.mission_id)"))).scalar_one()

    check("independent post-cleanup verification: 0 P15-tagged missions remain", remaining_missions == 0, f"{remaining_missions} remain")
    check("independent post-cleanup verification: 0 orphaned runtime_sessions remain", remaining_sessions == 0, f"{remaining_sessions} remain")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main() -> int:
    print(f"P15 multi-process concurrency proof — run id {RUN_ID}, database={os.environ['DATABASE_URL']}")
    worker_a = Worker("A")
    worker_b = Worker("B")
    worker_c = Worker("C")
    try:
        case_1_double_approval_race(worker_a, worker_b)
        case_2_double_execution_idempotency_race(worker_a, worker_b)
        case_3_reconciliation_and_crash_boundary(worker_a, worker_b)
        case_4_admission_race_tight_limit(limit=3, concurrency=10)
        case_5_token_expiry_race(worker_a, worker_b, worker_c)
    finally:
        worker_a.stop()
        worker_b.stop()
        worker_c.stop()
        asyncio.run(_cleanup_and_verify())

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"RESULT: FAIL — {len(FAILURES)} check(s) failed:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("RESULT: PASS — all checks passed across real, separate OS processes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
