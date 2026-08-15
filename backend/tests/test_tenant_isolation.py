"""
P17 — the exact defect P16 proved live (docs/prime-agent-integration/
27-multi-tenancy-and-multi-host-safety.md), now closed: a request belonging
to one tenant must be invisible to, and undecidable by, a user in a
different tenant, through the real HTTP surface AND at the ORM query level.

Two real tenants, two real users (one of the five permanent seeded accounts
for tenant A -- the default tenant everything already belongs to -- plus a
freshly created, temporary second tenant and user for tenant B, cleaned up
by each test's own fixture). Real Postgres throughout; ServiceNow is never
reached (every decision here is `reject`, which has no external effect --
same choice scripts/p16_tenant_boundary_proof.py made and for the same
reason).
"""

import uuid

import pytest
from sqlalchemy import text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from backend.app.rbac import Role, User, create_access_token
from contracts import Capability
from db.engine import async_session_factory
from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from db.models.tenant import DEFAULT_TENANT_ID, TenantMembershipRow, TenantRow
from db.tenancy import use_all_tenants, use_tenant
from orchestrate.runtime.prime import token_expiry

EXPENSIVE = {"summary": "tenant isolation test", "_estimated_cost_usd": 300_000.0}


@pytest.fixture(autouse=True)
async def _clean():
    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()
    yield


@pytest.fixture
async def tenant_b():
    """A real second tenant with a real member user, created fresh for each
    test and torn down after -- never touches the 5 permanent seeded
    accounts or the default tenant."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with async_session_factory() as db:
        db.add(TenantRow(tenant_id=tenant_id, name="Tenant B", slug=f"tenant-b-{tenant_id.hex[:8]}"))
        db.add(TenantMembershipRow(tenant_id=tenant_id, user_id=user_id))
        await db.commit()
    yield tenant_id, user_id
    async with async_session_factory() as db:
        await db.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :t"), {"t": tenant_id})
        await db.execute(text("DELETE FROM tenants WHERE tenant_id = :t"), {"t": tenant_id})
        await db.commit()


def _headers_for(user_id: uuid.UUID, tenant_id: uuid.UUID, *, role=Role.EXECUTIVE, limit=1_000_000.0):
    user = User(
        user_id=str(user_id), username=f"u-{user_id.hex[:8]}", display_name="test",
        role=role, approval_limit_usd=limit, tenant_ids=[str(tenant_id)],
    )
    return {"Authorization": f"Bearer {create_access_token(user)}"}


async def _mission_and_session(tenant_id: uuid.UUID, capability=Capability.NOTIFY_IT_HELPDESK):
    async with async_session_factory() as db:
        mission = MissionRow(
            title="tenant isolation test", objective="o", domain="it",
            allowed_capabilities=[capability.value], status="running", tenant_id=tenant_id,
        )
        db.add(mission)
        await db.flush()
        token = "tok-" + uuid.uuid4().hex
        sess = RuntimeSessionRow(
            mission_id=mission.mission_id, tenant_id=tenant_id, state="running",
            token_hash=hash_token(token), token_expires_at=token_expiry(1800.0),
        )
        db.add(sess)
        await db.commit()
        return mission.mission_id, sess.session_id, token


@pytest.fixture
def _as_runtime(monkeypatch):
    def present(token):
        monkeypatch.setattr(mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"})
    return present


async def _park_a_request(_as_runtime, token) -> str:
    _as_runtime(token)
    parked = await request_capability.fn("NotifyITHelpdesk", dict(EXPENSIVE))
    assert parked["status"] == "pending_approval", parked
    return parked["request_id"]


async def test_a_tenant_a_request_carries_the_default_tenant_id(_as_runtime):
    """Baseline: the real creation path (mcp_gateway.request_capability)
    denormalizes tenant_id from the mission onto the parked row -- the
    exact column the P16-demonstrated defect needed and did not have."""
    _, _, token = await _mission_and_session(DEFAULT_TENANT_ID)
    request_id = await _park_a_request(_as_runtime, token)

    with use_all_tenants():
        async with async_session_factory() as db:
            row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
    assert row.tenant_id == DEFAULT_TENANT_ID


async def test_user_a_cannot_list_user_bs_request(client, _as_runtime, tenant_b):
    tenant_b_id, user_b_id = tenant_b
    _, _, token = await _mission_and_session(tenant_b_id)
    request_id = await _park_a_request(_as_runtime, token)

    headers_a = _headers_for(uuid.uuid4(), DEFAULT_TENANT_ID)
    listing = client.get("/runtime/capability-requests", headers=headers_a).json()
    assert request_id not in {r["requestId"] for r in listing["requests"]}


async def test_user_a_cannot_get_user_bs_request_by_id(client, _as_runtime, tenant_b):
    tenant_b_id, user_b_id = tenant_b
    _, _, token = await _mission_and_session(tenant_b_id)
    request_id = await _park_a_request(_as_runtime, token)

    headers_a = _headers_for(uuid.uuid4(), DEFAULT_TENANT_ID)
    resp = client.get(f"/runtime/capability-requests/{request_id}", headers=headers_a)
    assert resp.status_code == 404


async def test_user_a_cannot_reject_user_bs_request(client, _as_runtime, tenant_b):
    tenant_b_id, user_b_id = tenant_b
    _, _, token = await _mission_and_session(tenant_b_id)
    request_id = await _park_a_request(_as_runtime, token)

    headers_a = _headers_for(uuid.uuid4(), DEFAULT_TENANT_ID)
    resp = client.post(f"/runtime/capability-requests/{request_id}/reject", headers=headers_a, json={})
    assert resp.status_code == 404

    with use_all_tenants():
        async with async_session_factory() as db:
            row = await db.get(CapabilityRequestRow, uuid.UUID(request_id))
    assert row.status == "pending_approval", "tenant A's refused decision must not have touched the row"


async def test_user_b_cannot_reach_user_as_request(client, _as_runtime, tenant_b):
    tenant_b_id, user_b_id = tenant_b
    _, _, token = await _mission_and_session(DEFAULT_TENANT_ID)
    request_id = await _park_a_request(_as_runtime, token)

    headers_b = _headers_for(user_b_id, tenant_b_id)
    resp = client.get(f"/runtime/capability-requests/{request_id}", headers=headers_b)
    assert resp.status_code == 404
    resp = client.post(f"/runtime/capability-requests/{request_id}/reject", headers=headers_b, json={})
    assert resp.status_code == 404


async def test_user_b_can_reach_their_own_tenants_request(client, _as_runtime, tenant_b):
    """The inverse of every test above: tenant scoping refuses cross-tenant
    access without refusing same-tenant access -- this is isolation, not a
    blanket lockout."""
    tenant_b_id, user_b_id = tenant_b
    _, _, token = await _mission_and_session(tenant_b_id)
    request_id = await _park_a_request(_as_runtime, token)

    headers_b = _headers_for(user_b_id, tenant_b_id)
    listing = client.get("/runtime/capability-requests", headers=headers_b).json()
    assert request_id in {r["requestId"] for r in listing["requests"]}

    resp = client.get(f"/runtime/capability-requests/{request_id}", headers=headers_b)
    assert resp.status_code == 200

    resp = client.post(f"/runtime/capability-requests/{request_id}/reject", headers=headers_b, json={"reason": "test"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "denied"


async def test_the_orm_query_itself_is_tenant_scoped_not_just_the_endpoint(tenant_b):
    """Goes underneath the router entirely: db/tenancy.py's do_orm_execute
    filter must make tenant B's row invisible to a plain ORM select scoped
    to tenant A, independent of any endpoint-level logic."""
    tenant_b_id, _ = tenant_b
    async with async_session_factory() as db:
        mission = MissionRow(
            title="orm-level isolation", objective="o", domain="it",
            allowed_capabilities=[], status="running", tenant_id=tenant_b_id,
        )
        db.add(mission)
        await db.commit()
        mission_id = mission.mission_id

    from sqlalchemy import select

    with use_tenant(DEFAULT_TENANT_ID):
        async with async_session_factory() as db:
            row = await db.get(MissionRow, mission_id)
            assert row is None
            rows = (await db.execute(select(MissionRow).where(MissionRow.mission_id == mission_id))).scalars().all()
            assert rows == []

    with use_tenant(tenant_b_id):
        async with async_session_factory() as db:
            row = await db.get(MissionRow, mission_id)
            assert row is not None
            assert row.tenant_id == tenant_b_id
