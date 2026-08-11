"""
P9 — EXPLICIT LIVE CRASH/RECOVERY DEMONSTRATION — mutates a real ServiceNow
instance. Creates exactly ONE marked record.

    set -a && source .env && set +a
    ./.venv/bin/python scripts/p9_crash_recovery_e2e.py

Proves the exact scenario the P9 instructions singled out by name, against a
REAL ServiceNow instance rather than a mocked transport:

    a Tier 2 request is approved
    -> the REAL external side effect succeeds (a real incident is created)
    -> ADOS "dies" before recording that locally (simulated: the same
       BaseException-injection technique the mocked test suite uses)
    -> the request row is left durably `executing`, not silently reset
    -> a retry/second-approval is refused automatically
    -> reconciliation, using ONLY the row's own canonical request_id, finds
       the real record and resolves the row to `executed`
    -> the real external side effect occurred EXACTLY ONCE

SCOPE, STATED PLAINLY. This does not re-run a full containerized Prime Agent
— P6/P7 already proved that path live, repeatedly. What P9 adds is the
crash-recovery mechanism at the gateway/approval/reconciliation layer, which
behaves identically regardless of whether the parked request came from a live
agent or (as here) a directly-seeded mission/session row. Manufacturing a
full container run to reach the same approval endpoint would add cost and
risk without adding evidence about the thing actually under test here.

Every fact this script prints is re-derived independently afterward, not
trusted from the script's own narrative — see the final section.
"""

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import select

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token
from backend.app.rbac import Role, User
from backend.app.routers import runtime_approvals
from backend.app.routers.runtime_approvals import approve_capability_request
from db.engine import async_session_factory, engine
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from integrations.connectors.servicenow import ServiceNowConnector
from orchestrate.runtime.build_identity import REPO_ROOT, StaleGatewayError, verify_build_matches, compute_build_revision
from orchestrate.runtime.capability_execution import STATUS_EXECUTED, STATUS_EXECUTING, STATUS_OUTCOME_UNKNOWN
from orchestrate.runtime.capability_reconcile import mark_stalled_executions_unknown, reconcile_outcome_unknown
from orchestrate.runtime.prime import token_expiry

MARKER = f"[ADOS PRIME-AGENT INTEGRATION TEST] P9-{uuid.uuid4().hex[:8]}"
TABLE = "incident"

_timeline: list = []


def _mark(label: str, detail: str = "") -> float:
    now = time.time()
    _timeline.append((now, label, detail))
    print(f"    [{label}] {detail}")
    return now


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


class RunFailed(Exception):
    """A demonstration that did not demonstrate what it claims to."""


async def _connector() -> ServiceNowConnector:
    c = ServiceNowConnector()
    if not c.is_configured():
        raise RunFailed(
            "ServiceNow not configured — set SERVICENOW_INSTANCE_URL/USERNAME/PASSWORD "
            "(see .env.example). This script refuses to fall back to a simulation."
        )
    return c


async def _sweep_marker(connector: ServiceNowConnector) -> list:
    ok, records = await connector.find_by_request_id(TABLE, MARKER)
    if not ok:
        raise RunFailed(f"could not query ServiceNow for the sweep marker: {records}")
    return records


async def _seed_mission() -> tuple:
    async with async_session_factory() as db:
        mission = MissionRow(
            title="P9 crash/recovery", objective="o", domain="it",
            allowed_capabilities=["NotifyITHelpdesk"], status="running",
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, state="running", token_hash=hash_token(token),
            # P10: this script used to leave token_expires_at NULL, unlike
            # its sibling e2e scripts (prime_agent_servicenow_e2e.py,
            # prime_agent_approval_e2e.py) — every real production session
            # has set this since P6-D, so a NULL row this script produced
            # was never distinguishable from a genuine pre-P6-D fossil,
            # only discoverable by reading this file. Debugging runs of
            # this exact script (crashed mid-iteration, by design — that is
            # what it exists to simulate) are what actually populated the
            # NULL-expiry rows re-derivation found in the dev database
            # during P10. Same lifecycle as the production path now.
            token_expires_at=token_expiry(1800.0),
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


def _as_runtime(token: str) -> None:
    mcp_gateway.get_http_headers = lambda: {"authorization": f"Bearer {token}"}


async def _park(token: str) -> str:
    _as_runtime(token)
    parked = await mcp_gateway.request_capability.fn(
        "NotifyITHelpdesk",
        {"summary": f"{MARKER} pool exhaustion", "_estimated_cost_usd": 300_000.0},
    )
    if parked["status"] != "pending_approval":
        raise RunFailed(f"expected pending_approval, got {parked}")
    return parked["request_id"]


async def _row(request_id: str) -> CapabilityRequestRow:
    async with async_session_factory() as db:
        return await db.get(CapabilityRequestRow, uuid.UUID(request_id))


class _FakeRequest:
    class app:
        class state:
            pass


def _approver() -> User:
    return User(
        user_id="u-p9", username="p9-approver", display_name="P9 Approver",
        role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0,
    )


async def _approve(request_id: str):
    async with async_session_factory() as db:
        return await approve_capability_request(
            request_id, _FakeRequest(), current_user=_approver(), session=db,
        )


async def main() -> Dict[str, Any]:
    result: Dict[str, Any] = {"marker": MARKER}

    _rule("PRE-FLIGHT")
    expected = compute_build_revision(REPO_ROOT, source=f"expected-source:{REPO_ROOT}")
    _mark("BUILD", f"this process's own source: {expected.label}")
    connector = await _connector()
    _mark("SERVICENOW", "configured")

    pre_existing = await _sweep_marker(connector)
    if pre_existing:
        raise RunFailed(f"marker already present before this run started: {pre_existing}")
    _mark("SWEPT CLEAN", "0 pre-existing records carrying this run's marker")

    _rule("PARK A TIER 2 REQUEST")
    mission_id, session_id, token = await _seed_mission()
    request_id = await _park(token)
    row = await _row(request_id)
    result["request_id"] = request_id
    _mark("PENDING", f"request {request_id} tier={row.policy_tier} risk={row.risk_class}")
    if int(row.policy_tier or 0) < 2:
        raise RunFailed(f"expected tier 2, got {row.policy_tier}")

    _rule("APPROVE, WITH A SIMULATED CRASH AFTER THE REAL EXTERNAL EFFECT")
    real_execute = mcp_gateway._execute_capability

    async def crash_after_success(*args, **kwargs):
        outcome = await real_execute(*args, **kwargs)  # THE REAL SERVICENOW CALL
        raise asyncio.CancelledError("simulated ADOS crash: after external success, before commit")

    runtime_approvals._execute_capability = crash_after_success
    try:
        await _approve(request_id)
        raise RunFailed("approval did not raise — the simulated crash did not fire")
    except asyncio.CancelledError:
        _mark("CRASHED", "simulated — the real external call already returned by this point")
    finally:
        runtime_approvals._execute_capability = real_execute

    row = await _row(request_id)
    result["status_after_crash"] = row.status
    if row.status != STATUS_EXECUTING:
        raise RunFailed(f"expected the row durably at 'executing' after the crash, got {row.status!r}")
    _mark("DURABLY EXECUTING", f"request {request_id} — not reset to pending_approval")

    # The real record exists NOW, even though ADOS does not yet know it.
    created = await _sweep_marker(connector)
    if len(created) != 1:
        raise RunFailed(f"expected exactly 1 real record after the external call, found {len(created)}: {created}")
    result["created_number"] = created[0].get("number")
    result["created_sys_id"] = created[0].get("sys_id")
    _mark("REAL RECORD EXISTS", f"{created[0].get('number')} ({created[0].get('sys_id')}) — ADOS's own row does not know this yet")

    _rule("AUTOMATIC RE-EXECUTION IS REFUSED, BEFORE ANY RECONCILIATION")
    try:
        await _approve(request_id)
        raise RunFailed("a second approval of a durably-executing request was NOT refused")
    except Exception as exc:  # HTTPException(409)
        if getattr(exc, "status_code", None) != 409:
            raise RunFailed(f"expected HTTP 409 on retry, got {exc!r}") from exc
    _mark("RETRY REFUSED", "HTTP 409 — the row is not pending_approval")

    _rule("RESTART / RECONCILE")
    stalled = await mark_stalled_executions_unknown(async_session_factory, stall_seconds=0)
    if [s.request_id for s in stalled] != [uuid.UUID(request_id)]:
        raise RunFailed(f"stall detection did not pick up this row: {stalled}")
    row = await _row(request_id)
    result["status_after_stall_detection"] = row.status
    _mark("OUTCOME_UNKNOWN", f"request {request_id} — refuses automatic execution, needs reconciliation")

    resolved = await reconcile_outcome_unknown(async_session_factory, connector=connector)
    mine = [o for o in resolved if str(o.request_id) == request_id]
    if not mine or not mine[0].resolved:
        raise RunFailed(f"reconciliation did not resolve this row: {resolved}")
    _mark("RECONCILED", mine[0].detail)

    row = await _row(request_id)
    result["status_final"] = row.status
    if row.status != STATUS_EXECUTED:
        raise RunFailed(f"expected 'executed' after reconciliation, got {row.status!r}")

    _rule("INDEPENDENT VERIFICATION — fresh queries, not this script's own narrative")

    async with async_session_factory() as db:
        fresh_row = (
            await db.execute(select(CapabilityRequestRow).where(CapabilityRequestRow.request_id == uuid.UUID(request_id)))
        ).scalar_one()
    _mark("POSTGRES (fresh session)", f"status={fresh_row.status} reconciled_match={fresh_row.result.get('reconciled_match')}")
    if fresh_row.status != STATUS_EXECUTED:
        raise RunFailed("independent Postgres read does not show 'executed'")

    ok, fetched = await connector.fetch_record(TABLE, fresh_row.result["reconciled_match"]["sys_id"])
    if not ok:
        raise RunFailed(f"independent ServiceNow read-back failed: {fetched}")
    if request_id not in fetched.get("description", ""):
        raise RunFailed("the independently-fetched record does not contain this row's own canonical request_id")
    _mark("SERVICENOW (fresh GET)", f"{fetched.get('number')} description contains request_id={request_id}: PRESENT")

    final_sweep = await _sweep_marker(connector)
    if len(final_sweep) != 1:
        raise RunFailed(f"expected exactly 1 record carrying the marker at cleanup time, found {len(final_sweep)}")
    result["external_record_count"] = len(final_sweep)
    _mark("RECORD COUNT", f"exactly 1 real record exists for this entire run — no duplicate")

    _rule("CLEANUP")
    close_ok, close_detail = await connector.resolve_record(
        TABLE, fresh_row.result["reconciled_match"]["sys_id"],
        close_notes=f"P9 crash/recovery demonstration complete — {MARKER}",
    )
    if not close_ok:
        raise RunFailed(f"cleanup failed to close the record: {close_detail} — sys_id {fresh_row.result['reconciled_match']['sys_id']}")
    _mark("CLOSED", f"state={close_detail}")

    ok, reread = await connector.fetch_record(TABLE, fresh_row.result["reconciled_match"]["sys_id"])
    result["final_state"] = reread.get("state") if ok else None
    _mark("RE-READ AFTER CLOSE", f"state={result['final_state']}")

    swept_after_close = await _sweep_marker(connector)
    open_after_close = [r for r in swept_after_close if r.get("state") not in ("7", "6")]
    if open_after_close:
        raise RunFailed(f"open marked records remain after cleanup: {open_after_close}")
    _mark("SWEPT CLEAN", "0 open records carrying this run's marker remain")

    result["timeline"] = [(t - _timeline[0][0], label, detail) for t, label, detail in _timeline]
    return result


if __name__ == "__main__":
    try:
        outcome = asyncio.run(main())
        _rule("PASS")
        for key in ("request_id", "created_number", "status_after_crash", "status_after_stall_detection", "status_final", "external_record_count", "final_state"):
            print(f"  {key}: {outcome.get(key)}")
        asyncio.run(engine.dispose())
        sys.exit(0)
    except RunFailed as e:
        _rule("*** RUN FAILED ***")
        print(f"  {e}")
        sys.exit(1)
