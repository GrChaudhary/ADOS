"""
P16 — LIVE PROOF that no tenant/ownership boundary exists on the Prime Agent
capability-request/approval surface today.

    ./.venv/bin/python scripts/p16_tenant_boundary_proof.py

WHAT THIS PROVES, AND HOW
--------------------------
Real app object (backend.app.main:app, completely unmodified), real Postgres
(db.engine.async_session_factory — whatever DATABASE_URL is configured),
real bcrypt-verified /auth/login, real JWTs, real endpoint code
(backend/app/routers/runtime_approvals.py) — the only thing this script does
that a browser could not is create the mission/session/capability-request
rows up front, standing in for a real Prime Agent mission having done so.

Two distinct, real, differently-provisioned seeded accounts stand in for
"tenant A" and "tenant B" — the closest real analogue this codebase has,
since IT HAS NO TENANT CONCEPT AT ALL (confirmed by source review: no
tenant_id/org_id/account_id column exists anywhere in db/models/, and
MissionRow.created_by is never set to an end user's identity by the one real
mission-creation path, integrations/connectors/prime_runtime.py — it is
always "system"). If ADOS had ownership-based isolation, "marcus" having no
relationship whatsoever to a request would be refused everything below with
403/404. It is not.

Uses httpx.ASGITransport against the real FastAPI app object (in-process,
not a separate network hop) — the right rigor for an AUTHORIZATION-LOGIC
boundary, not a concurrency race: every line of RBAC, routing, and Postgres
code the real server would run is exercised for real, network transport is
not the property under test. See docs/prime-agent-integration/
27-multi-tenancy-and-multi-host-safety.md for why this is classified TESTED
(not DEMONSTRATED-with-two-hosts) evidence and what would upgrade it.

Creates no external (ServiceNow) side effect: the proof ends at `reject`,
which the router's own docstring states has no external effect ("nothing
executes"), and `reject` shares the exact same three authorization gates
`approve` does (_load_pending_or_404, _live_session_or_409,
authorize_governance_decision) — so it demonstrates the identical missing
check without ever calling a connector.

Cleans up every row it creates and independently re-verifies their absence.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import select

from backend.app.main import app
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow

MARKER = f"p16-tenant-proof-{uuid.uuid4().hex[:8]}"


class RunFailed(RuntimeError):
    pass


def _check(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise RunFailed(label)


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    r = await client.post("/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        raise RunFailed(f"could not log in as {username}: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


async def _seed_request() -> tuple:
    """Stands in for a real Prime Agent mission — same shape a real one
    leaves behind, none of it attributable to any specific end user (real
    missions never are, see module docstring)."""
    async with async_session_factory() as db:
        mission = MissionRow(
            title=f"[{MARKER}] simulated mission",
            objective="simulated — created directly by the proof script",
            domain="it",
            allowed_capabilities=["NotifyITHelpdesk"],
            status="running",
            created_by="system",
        )
        db.add(mission)
        await db.flush()

        session = RuntimeSessionRow(
            mission_id=mission.mission_id,
            state="running",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(session)
        await db.flush()

        request = CapabilityRequestRow(
            session_id=session.session_id,
            mission_id=mission.mission_id,
            capability="NotifyITHelpdesk",
            arguments={"summary": f"[{MARKER}] test", "_estimated_cost_usd": 0.0},
            status="pending_approval",
            policy_tier=1,
            risk_class="medium",
        )
        db.add(request)
        await db.commit()
        return mission.mission_id, session.session_id, request.request_id


async def _cleanup(mission_id, session_id, request_id) -> None:
    async with async_session_factory() as db:
        row = await db.get(CapabilityRequestRow, request_id)
        if row is not None:
            await db.delete(row)
        row = await db.get(RuntimeSessionRow, session_id)
        if row is not None:
            await db.delete(row)
        row = await db.get(MissionRow, mission_id)
        if row is not None:
            await db.delete(row)
        await db.commit()


async def _verify_gone(mission_id, session_id, request_id) -> None:
    async with async_session_factory() as db:
        remaining = (
            await db.execute(
                select(MissionRow.mission_id).where(MissionRow.mission_id == mission_id)
            )
        ).scalar_one_or_none()
    _check(remaining is None, "independent re-query: mission fully removed after cleanup")


async def main() -> int:
    print(f"=== P16 tenant-boundary proof ({MARKER}) ===\n")
    mission_id, session_id, request_id = await _seed_request()
    print(f"seeded mission={mission_id} session={session_id} request={request_id}")
    print("owning identity on every row: created_by='system' (no end user) — the")
    print("real-world starting point, since Prime Agent missions are never")
    print("attributed to an individual user by the one real creation path.\n")

    failures = 0
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p16-proof") as client:
            token_emma = await _login(client, "emma", "password123")
            token_marcus = await _login(client, "marcus", "password123")
            print("logged in as two real, distinct, unrelated seeded accounts: emma and marcus\n")

            headers_emma = {"Authorization": f"Bearer {token_emma}"}
            headers_marcus = {"Authorization": f"Bearer {token_marcus}"}

            print("-- as emma, who created nothing and has no recorded relationship to this request --")
            r = await client.get("/runtime/capability-requests", headers=headers_emma)
            ids = {row["requestId"] for row in r.json()["requests"]}
            _check(r.status_code == 200 and str(request_id) in ids,
                   "GET /runtime/capability-requests (global list, no filter) includes the request")

            r = await client.get(f"/runtime/capability-requests/{request_id}", headers=headers_emma)
            _check(r.status_code == 200, "GET .../{id} returns full detail to an unrelated user")
            _check(r.json()["arguments"].get("summary", "").startswith(f"[{MARKER}]"),
                   "detail includes the mission's real argument content (not redacted)")

            print("\n-- as marcus, an equally unrelated second account --")
            r = await client.get(f"/runtime/capability-requests/{request_id}", headers=headers_marcus)
            _check(r.status_code == 200, "marcus can independently read the same request in full")

            print("\n-- as emma: decide it (reject — zero external side effect, same auth gates as approve) --")
            r = await client.post(
                f"/runtime/capability-requests/{request_id}/reject",
                headers=headers_emma, json={"reason": f"[{MARKER}] proof decision"},
            )
            _check(r.status_code == 200, "emma's decision is accepted (no ownership check anywhere in the path)")
            _check(r.json().get("decidedBy") == "user:emma", "row now durably attributes the decision to emma")

        async with async_session_factory() as db:
            row = await db.get(CapabilityRequestRow, request_id)
        _check(row is not None and row.status == "denied" and row.decided_by == "user:emma",
               "independent DB re-read confirms: status=denied, decided_by=user:emma")

    except RunFailed:
        failures += 1
    finally:
        print("\n-- cleanup --")
        await _cleanup(mission_id, session_id, request_id)
        await _verify_gone(mission_id, session_id, request_id)

    print()
    if failures:
        print("RESULT: proof did not run to completion as expected — see FAIL lines above.")
        return 1

    print("RESULT: CONFIRMED — an authenticated user with zero relationship to a mission")
    print("can read its full detail and unilaterally decide its pending capability request.")
    print("Authorization here is role/tier-based only; there is no tenant or ownership")
    print("boundary anywhere on this path. This is the expected, honest finding for a")
    print("system with no tenant model — not a defect in emma's or marcus's role checks.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
