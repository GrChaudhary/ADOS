"""
P18 — mission creation / tenant attribution.

P16/P17 both concluded "no user-facing mission-creation endpoint exists"
by grepping for a direct Python caller of `RunPrimeRLMAgent` (there is
none). That grep missed a real one: `POST /capabilities/invoke`
(backend/app/routers/capabilities.py, predates the Prime Agent
integration -- docs/006-integration-hub.md) dispatches by capability
*value*, not by a direct call, and any authenticated user can name
`RunPrimeRLMAgent` in the request body. `PrimeRuntimeConnector._run()`
(integrations/connectors/prime_runtime.py) used to stamp every mission it
created with the hardcoded default tenant regardless of who called it --
harmless while only one tenant has any users, a real cross-tenant
misattribution the moment a second tenant does (tenant B's mission would
land in tenant A's queue, visible to tenant A's approvers and invisible to
tenant B's own).

These tests exercise the fix directly against `PrimeRuntimeConnector`
(the same pattern test_prime_agent.py's own
`test_a_stale_process_refuses_the_mission_before_creating_any_row` already
uses) rather than through a real `docker run` -- `PrimeAgentRuntime.start`
is monkeypatched to fail immediately, after the mission row this test
actually cares about has already been created and committed, so no real
container is ever touched.
"""

import uuid

import pytest
from sqlalchemy import select, text

from contracts import Capability, CapabilityCall, GovernanceInfo, PolicyTier
from db.engine import async_session_factory
from db.models.mission import MissionRow
from db.models.tenant import DEFAULT_TENANT_ID, TenantMembershipRow, TenantRow
from db.tenancy import use_all_tenants, use_tenant
from integrations.connectors.prime_runtime import PrimeRuntimeConnector
from orchestrate.runtime.prime import PrimeAgentRuntime


class _StartRefused(Exception):
    pass


async def _start_refused(self, spec, token):
    raise _StartRefused("test: never actually start a container")


@pytest.fixture
async def tenant_b():
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


def _call(marker: str) -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.RUN_PRIME_RLM_AGENT,
        input={"prompt": marker, "domain": "it"},
        requested_by="test-caller",
        incident_id="INC-P18-TEST",
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


async def _mission_for_marker(marker: str) -> MissionRow:
    with use_all_tenants():
        async with async_session_factory() as db:
            row = (
                await db.execute(select(MissionRow).where(MissionRow.objective == marker))
            ).scalar_one()
            return row


async def test_no_tenant_context_falls_back_to_the_default_tenant(monkeypatch):
    """Every real non-HTTP caller today (MOA/internal code) never resolves
    a tenant context -- must keep working exactly as before P18."""
    monkeypatch.setattr(PrimeAgentRuntime, "start", _start_refused)
    marker = f"p18-no-context-{uuid.uuid4()}"

    connector = PrimeRuntimeConnector()
    response = await connector.execute(_call(marker))
    assert response.status.value == "failed"  # _StartRefused, not a real run

    row = await _mission_for_marker(marker)
    assert row.tenant_id == DEFAULT_TENANT_ID


async def test_a_resolved_caller_tenant_is_stamped_onto_the_mission(monkeypatch, tenant_b):
    """The actual P18 fix: when the call chain that reaches this connector
    resolved a real tenant (as backend/app/routers/capabilities.py's
    /invoke now does via get_tenant_context), that tenant -- not the
    default -- ends up on the mission row."""
    monkeypatch.setattr(PrimeAgentRuntime, "start", _start_refused)
    tenant_b_id, _ = tenant_b
    marker = f"p18-tenant-b-{uuid.uuid4()}"

    with use_tenant(tenant_b_id):
        connector = PrimeRuntimeConnector()
        response = await connector.execute(_call(marker))
    assert response.status.value == "failed"

    row = await _mission_for_marker(marker)
    assert row.tenant_id == tenant_b_id
    assert row.tenant_id != DEFAULT_TENANT_ID


async def test_invoke_capability_resolves_the_callers_tenant_before_reaching_the_connector(
    client, monkeypatch, tenant_b
):
    """End-to-end through the real, reachable HTTP path this phase found:
    POST /capabilities/invoke -> IntegrationHub.invoke() ->
    PrimeRuntimeConnector -- proving the tenant context set by
    get_tenant_context (backend/app/tenancy.py) on the /invoke route
    really does propagate all the way to the connector via the plain
    `await` call chain, with no new plumbing through CapabilityCall."""
    from backend.app.rbac import Role, User, create_access_token

    monkeypatch.setattr(PrimeAgentRuntime, "start", _start_refused)
    tenant_b_id, user_b_id = tenant_b
    marker = f"p18-http-invoke-{uuid.uuid4()}"

    user = User(
        user_id=str(user_b_id), username="tenant-b-caller", display_name="test",
        role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0, tenant_ids=[str(tenant_b_id)],
    )
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}

    body = {
        "capability": "RunPrimeRLMAgent",
        "incidentId": "INC-P18-HTTP",
        "requestedBy": "tenant-b-caller",
        "input": {"prompt": marker, "domain": "it"},
        "governance": {"policyTier": 0, "approvedBy": None},
    }
    response = client.post("/capabilities/invoke", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"  # _StartRefused, not a real run

    row = await _mission_for_marker(marker)
    assert row.tenant_id == tenant_b_id


async def test_invoke_capability_requires_a_resolvable_tenant(client):
    """A caller with no tenant membership at all cannot reach the endpoint
    -- fail-closed, matching every other tenant-scoped entry point, not a
    silent fall-through to the default tenant."""
    from backend.app.rbac import Role, User, create_access_token

    user = User(
        user_id=str(uuid.uuid4()), username="no-tenant", display_name="test",
        role=Role.EXECUTIVE, approval_limit_usd=1_000_000.0, tenant_ids=[],
    )
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    body = {
        "capability": "NotifyOperator",
        "incidentId": "inc-p18-no-tenant",
        "requestedBy": "orchestrator",
        "input": {"message": "test"},
        "governance": {"policyTier": 0, "approvedBy": None},
    }
    response = client.post("/capabilities/invoke", json=body, headers=headers)
    assert response.status_code == 403
