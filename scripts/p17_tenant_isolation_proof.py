"""
P17 — LIVE PROOF that cross-tenant access is now impossible on the exact
surface scripts/p16_tenant_boundary_proof.py proved it was NOT.

    ./.venv/bin/python scripts/p17_tenant_isolation_proof.py

Real, unmodified backend.app.main:app; real Postgres; real bcrypt-verified
/auth/login for tenant A's user (one of the five permanent seeded
accounts); a freshly created, temporary second tenant and user for tenant
B (created directly, cleaned up at the end — the same convention P16's
proof used to simulate "what a real Prime Agent mission leaves behind",
since there is still no user-facing "create a mission" HTTP endpoint to
drive this through end to end). Every decision here is `reject` — zero
external (ServiceNow) side effect, and it shares the identical three
authorization gates `approve` does, so the finding is identical either way.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import text

from backend.app.main import app
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from db.models.tenant import DEFAULT_TENANT_ID, TenantMembershipRow, TenantRow
from db.tenancy import use_all_tenants

MARKER = f"p17-tenant-isolation-{uuid.uuid4().hex[:8]}"


class RunFailed(RuntimeError):
    pass


def _check(condition: bool, label: str) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        raise RunFailed(label)


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    r = await client.post("/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        raise RunFailed(f"could not log in as {username}: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


async def _seed_request(tenant_id: uuid.UUID, marker: str) -> tuple:
    async with async_session_factory() as db:
        mission = MissionRow(
            title=f"[{marker}] simulated mission", objective="simulated", domain="it",
            allowed_capabilities=["NotifyITHelpdesk"], status="running", created_by="system",
            tenant_id=tenant_id,
        )
        db.add(mission)
        await db.flush()
        session = RuntimeSessionRow(
            mission_id=mission.mission_id, tenant_id=tenant_id, state="running",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(session)
        await db.flush()
        request = CapabilityRequestRow(
            session_id=session.session_id, mission_id=mission.mission_id, tenant_id=tenant_id,
            capability="NotifyITHelpdesk",
            arguments={"summary": f"[{marker}] test", "_estimated_cost_usd": 0.0},
            status="pending_approval", policy_tier=1, risk_class="medium",
        )
        db.add(request)
        await db.commit()
        return mission.mission_id, session.session_id, request.request_id


async def main() -> int:
    print(f"=== P17 tenant-isolation proof ({MARKER}) ===\n")

    tenant_b_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    async with async_session_factory() as db:
        db.add(TenantRow(tenant_id=tenant_b_id, name=f"[{MARKER}] Tenant B", slug=f"tenant-b-{MARKER}"))
        db.add(TenantMembershipRow(tenant_id=tenant_b_id, user_id=user_b_id))
        await db.commit()
    print(f"created real tenant B ({tenant_b_id}) with one real member (user_id={user_b_id})")

    mission_a, session_a, request_a = await _seed_request(DEFAULT_TENANT_ID, MARKER + "-A")
    mission_b, session_b, request_b = await _seed_request(tenant_b_id, MARKER + "-B")
    print(f"seeded request A (tenant=default) = {request_a}")
    print(f"seeded request B (tenant=B)       = {request_b}\n")

    failures = 0
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p17-proof") as client:
            token_emma = await _login(client, "emma", "password123")
            headers_emma = {"Authorization": f"Bearer {token_emma}"}

            # "user B" has no real password (created directly, not through
            # /auth/login) -- exercised at the ORM/dependency level instead,
            # via a directly-minted token carrying its real tenant
            # membership, exactly as get_tenant_context would derive it from
            # a real login. This is the same "real auth, direct token
            # minting for a user with no interactive password" pattern nothing
            # else in this codebase's live-proof scripts needed until now,
            # since P17 is the first phase with a second tenant at all.
            from backend.app.rbac import Role, User, create_access_token
            user_b = User(
                user_id=str(user_b_id), username=f"tenant-b-user-{MARKER}", display_name="Tenant B User",
                role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0, tenant_ids=[str(tenant_b_id)],
            )
            headers_b = {"Authorization": f"Bearer {create_access_token(user_b)}"}

            print("-- as emma (tenant: default) --")
            r = await client.get("/runtime/capability-requests", headers=headers_emma)
            ids = {row["requestId"] for row in r.json()["requests"]}
            _check(str(request_a) in ids, "emma's list includes request A (same tenant)")
            _check(str(request_b) not in ids, "emma's list excludes request B (tenant B)")

            r = await client.get(f"/runtime/capability-requests/{request_b}", headers=headers_emma)
            _check(r.status_code == 404, "emma GET request B -> 404 (not 403 -- existence not revealed)")

            r = await client.post(f"/runtime/capability-requests/{request_b}/reject", headers=headers_emma, json={})
            _check(r.status_code == 404, "emma reject request B -> 404, no decision recorded")

            print("\n-- as tenant B's user (tenant: B) --")
            r = await client.get("/runtime/capability-requests", headers=headers_b)
            ids_b = {row["requestId"] for row in r.json()["requests"]}
            _check(str(request_b) in ids_b, "tenant B's list includes request B (own tenant)")
            _check(str(request_a) not in ids_b, "tenant B's list excludes request A (default tenant)")

            r = await client.get(f"/runtime/capability-requests/{request_a}", headers=headers_b)
            _check(r.status_code == 404, "tenant B GET request A -> 404")

            r = await client.post(f"/runtime/capability-requests/{request_a}/reject", headers=headers_b, json={})
            _check(r.status_code == 404, "tenant B reject request A -> 404, no decision recorded")

            print("\n-- tenant B correctly acting on its OWN request (isolation, not lockout) --")
            r = await client.post(
                f"/runtime/capability-requests/{request_b}/reject", headers=headers_b, json={"reason": f"[{MARKER}]"},
            )
            _check(r.status_code == 200 and r.json()["status"] == "denied", "tenant B can reject its own request B")

        with use_all_tenants():
            async with async_session_factory() as db:
                row_a = await db.get(CapabilityRequestRow, request_a)
                row_b = await db.get(CapabilityRequestRow, request_b)
        _check(row_a.status == "pending_approval", "request A untouched by every cross-tenant attempt")
        _check(row_b.status == "denied" and row_b.decided_by is not None, "request B correctly decided by its own tenant's user")

    except RunFailed:
        failures += 1
    finally:
        print("\n-- cleanup --")
        with use_all_tenants():
            async with async_session_factory() as db:
                for rid in (request_a, request_b):
                    row = await db.get(CapabilityRequestRow, rid)
                    if row is not None:
                        await db.delete(row)
                for sid in (session_a, session_b):
                    row = await db.get(RuntimeSessionRow, sid)
                    if row is not None:
                        await db.delete(row)
                for mid in (mission_a, mission_b):
                    row = await db.get(MissionRow, mid)
                    if row is not None:
                        await db.delete(row)
                await db.commit()
            async with async_session_factory() as db:
                await db.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :t"), {"t": tenant_b_id})
                await db.execute(text("DELETE FROM tenants WHERE tenant_id = :t"), {"t": tenant_b_id})
                await db.commit()

        with use_all_tenants():
            async with async_session_factory() as db:
                remaining = await db.get(MissionRow, mission_a)
                remaining_b = await db.get(MissionRow, mission_b)
        _check(remaining is None and remaining_b is None, "independent re-query: both missions fully removed")
        async with async_session_factory() as db:
            t = (await db.execute(text("SELECT count(*) FROM tenants WHERE tenant_id = :t"), {"t": tenant_b_id})).scalar_one()
        _check(t == 0, "independent re-query: tenant B fully removed")

    print()
    if failures:
        print("RESULT: proof did not run to completion as expected -- see FAIL lines above.")
        return 1

    print("RESULT: CONFIRMED -- two real tenants, two real users, real Postgres, real HTTP:")
    print("cross-tenant read/list/decide is refused (404, existence never revealed); same-tenant")
    print("access is unaffected. This is the exact surface scripts/p16_tenant_boundary_proof.py")
    print("proved had NO boundary at all -- that finding is now closed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
