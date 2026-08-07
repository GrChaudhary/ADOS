def test_invoke_capability_tier0_autonomous(client, auth_headers):
    call = {
        "capability": "NotifyOperator",
        "incidentId": "inc-test-2",
        "requestedBy": "orchestrator",
        "input": {"message": "line 3 tolerance drift detected"},
        "governance": {"policyTier": 0, "approvedBy": None},
    }

    response = client.post("/capabilities/invoke", json=call, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["connector"] == "console"


def test_invoke_capability_requires_auth(client):
    response = client.post("/capabilities/invoke", json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------
# Capability Manifest Registry REST surface — the registry
# (integrations/capability_manifest.py) predates these routes; this pins
# down that GET/POST actually reach the same instance backend/app/main.py
# constructs at startup (request.app.state.integration_hub.manifests),
# not a fresh disconnected one.
#
# These tests seed manifests by calling the registry directly (there's no
# admin-facing "propose" REST endpoint by design — an onboarding agent
# proposes, not an admin). That direct call and the HTTP requests below
# both need to run on the SAME asyncio event loop, since the Postgres
# connections involved are loop-bound (asyncpg) — the `client`/TestClient
# fixture from conftest.py runs the app on ITS OWN portal thread's loop,
# a different one than a plain `await` in an `async def` test would use,
# so mixing them here would risk a genuine "attached to a different loop"
# error. Using httpx.ASGITransport instead keeps everything (fixture
# setup, the direct registry call, and the HTTP calls) on one loop — safe
# for these non-streaming endpoints (unlike SSE, a plain request/response
# doesn't hit ASGITransport's full-buffering hang risk, see
# tests/test_events_stream_router.py's regression test for that
# distinction).
# ---------------------------------------------------------------------

import httpx
import pytest

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from contracts import PolicyTier
from integrations.capability_manifest import RiskProfileEntry

_MANIFEST_ADMIN_AUTH = {"Authorization": f"Bearer {create_access_token(User(user_id='test-admin', username='test-admin', display_name='Test Admin', role=Role.ADMIN, approval_limit_usd=1_000_000_000.0))}"}
_MANIFEST_MANAGER_AUTH = {"Authorization": f"Bearer {create_access_token(User(user_id='test-manager', username='test-manager', display_name='Test Manager', role=Role.MANAGER, approval_limit_usd=1_000_000.0))}"}


async def _propose(capability_id="test.read_ticket", proposed_by="onboarding-agent"):
    registry = app.state.integration_hub.manifests
    await registry.propose(
        capability_id,
        domain="support",
        version="1.0.0",
        source="github.com/x/y",
        risk_profile=[RiskProfileEntry(action="read", tier=PolicyTier.AUTONOMOUS, reasoning="read-only")],
        proposed_by=proposed_by,
    )
    return capability_id


@pytest.mark.asyncio
async def test_list_manifests_empty_by_default():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/capabilities/manifests", headers=_MANIFEST_ADMIN_AUTH)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_manifests_requires_auth():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/capabilities/manifests")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_promote_requires_sandbox_testing_first():
    async with app.router.lifespan_context(app):
        capability_id = await _propose()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/capabilities/manifests/{capability_id}/promote", headers=_MANIFEST_ADMIN_AUTH)
    assert response.status_code == 409  # PROPOSED, sandbox gate not passed — no fast-forward


@pytest.mark.asyncio
async def test_promote_after_sandbox_tested_activates():
    async with app.router.lifespan_context(app):
        capability_id = await _propose(proposed_by="onboarding-agent")
        registry = app.state.integration_hub.manifests
        await registry.record_sandbox_evidence(capability_id, "ran 12/12 checks", actor="onboarding-agent")

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/capabilities/manifests/{capability_id}/promote", headers=_MANIFEST_ADMIN_AUTH)
            assert response.status_code == 200
            assert response.json()["status"] == "active"

            listed = (await client.get("/capabilities/manifests", headers=_MANIFEST_ADMIN_AUTH)).json()
    entry = next(m for m in listed if m["capability_id"] == capability_id)
    assert entry["status"] == "active"
    assert entry["risk_level"] == "LOW"


@pytest.mark.asyncio
async def test_promote_forbidden_for_manager_role():
    async with app.router.lifespan_context(app):
        capability_id = await _propose()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/capabilities/manifests/{capability_id}/promote", headers=_MANIFEST_MANAGER_AUTH)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_disable_requires_active_status():
    async with app.router.lifespan_context(app):
        capability_id = await _propose()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/capabilities/manifests/{capability_id}/disable", headers=_MANIFEST_ADMIN_AUTH)
    assert response.status_code == 409  # still PROPOSED, nothing "in service" to pull


@pytest.mark.asyncio
async def test_disable_unknown_capability_404s():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/capabilities/manifests/does-not-exist/disable", headers=_MANIFEST_ADMIN_AUTH)
    assert response.status_code == 404


# ---------------------------------------------------------------------
# Real per-action risk-tier calibration (vision §5.2/§8.6) — the admin
# REST trigger for CapabilityManifestRegistry.calibrate_tier(). The
# method's own fail-closed rules (ACTIVE only, minimum usage_count, zero
# failure_count, strictly-safer target) are covered directly in
# tests/test_capability_manifest.py; this file only pins down the HTTP
# contract (RBAC, 404, 409-vs-200, and that a success actually mutates the
# manifest a follow-up GET sees).
# ---------------------------------------------------------------------

async def _activate(capability_id: str):
    registry = app.state.integration_hub.manifests
    await registry.record_sandbox_evidence(capability_id, "ran 12/12 checks", actor="onboarding-agent")
    await registry.activate(capability_id, actor="admin-1", reason="approved")


@pytest.mark.asyncio
async def test_calibrate_tier_forbidden_for_manager_role():
    async with app.router.lifespan_context(app):
        capability_id = await _propose()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/capabilities/manifests/{capability_id}/calibrate-tier",
                json={"target_tier": 1}, headers=_MANIFEST_MANAGER_AUTH,
            )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_calibrate_tier_unknown_capability_404s():
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/capabilities/manifests/does-not-exist/calibrate-tier",
                json={"target_tier": 1}, headers=_MANIFEST_ADMIN_AUTH,
            )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_calibrate_tier_409s_below_the_minimum_usage_count():
    async with app.router.lifespan_context(app):
        capability_id = await _propose()
        await _activate(capability_id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/capabilities/manifests/{capability_id}/calibrate-tier",
                json={"target_tier": 1}, headers=_MANIFEST_ADMIN_AUTH,
            )
    assert response.status_code == 409
    assert "needs at least" in response.json()["detail"]


@pytest.mark.asyncio
async def test_calibrate_tier_succeeds_and_is_visible_on_a_follow_up_get():
    async with app.router.lifespan_context(app):
        capability_id = await _propose()
        await _activate(capability_id)
        registry = app.state.integration_hub.manifests
        for _ in range(10):
            await registry.record_usage(capability_id)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/capabilities/manifests/{capability_id}/calibrate-tier",
                json={"target_tier": 1}, headers=_MANIFEST_ADMIN_AUTH,
            )
            assert response.status_code == 200, response.text
            assert response.json()["tier_override"] == 1

            listed = (await client.get("/capabilities/manifests", headers=_MANIFEST_ADMIN_AUTH)).json()
    entry = next(m for m in listed if m["capability_id"] == capability_id)
    assert entry["tier_override"] == 1
    assert entry["usage_count"] == 10
    assert entry["failure_count"] == 0
