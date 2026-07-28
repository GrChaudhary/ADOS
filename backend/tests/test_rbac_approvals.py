"""
RBAC authorization for incident approve/reject/escalate — backend/app/
routers/incidents.py's _authorize_decision(). Unit-tests the rule
directly against constructed User/PendingApproval objects (same pattern
tests/test_orchestrate.py already uses for DecisionOrchestrator's
_capability_for_option), plus one full HTTP round trip proving the 403
actually reaches the client through the real endpoint.
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.rbac import Role, User, create_access_token
from backend.app.routers.incidents import _authorize_decision
from contracts import Capability, PolicyTier
from orchestrate.governance import PendingApproval


def _user(role: Role, approval_limit_usd: float) -> User:
    return User(
        user_id=f"test-{role.value}",
        username=f"test-{role.value}",
        display_name=f"Test {role.value.title()}",
        role=role,
        approval_limit_usd=approval_limit_usd,
    )


def _pending(policy_tier: PolicyTier, estimated_cost_usd: float) -> PendingApproval:
    return PendingApproval(
        incident_id="INC-RBAC-TEST",
        capability=Capability.SCHEDULE_MAINTENANCE,
        policy_tier=policy_tier,
        confidence=0.85,
        summary="Test decision",
        estimated_cost_usd=estimated_cost_usd,
    )


def test_manager_approves_tier1_within_limit():
    manager = _user(Role.MANAGER, approval_limit_usd=250_000.0)
    pending = _pending(PolicyTier.APPROVAL_REQUIRED, estimated_cost_usd=100_000.0)
    _authorize_decision(manager, pending)  # does not raise


def test_manager_blocked_over_limit():
    manager = _user(Role.MANAGER, approval_limit_usd=1_000.0)
    pending = _pending(PolicyTier.APPROVAL_REQUIRED, estimated_cost_usd=100_000.0)
    with pytest.raises(HTTPException) as exc:
        _authorize_decision(manager, pending)
    assert exc.value.status_code == 403


def test_manager_blocked_on_tier2_regardless_of_limit():
    manager = _user(Role.MANAGER, approval_limit_usd=10_000_000.0)
    pending = _pending(PolicyTier.EXECUTIVE_APPROVAL, estimated_cost_usd=500.0)
    with pytest.raises(HTTPException) as exc:
        _authorize_decision(manager, pending)
    assert exc.value.status_code == 403


def test_executive_approves_tier2_within_limit():
    executive = _user(Role.EXECUTIVE, approval_limit_usd=5_000_000.0)
    pending = _pending(PolicyTier.EXECUTIVE_APPROVAL, estimated_cost_usd=1_000_000.0)
    _authorize_decision(executive, pending)  # does not raise


def test_auditor_blocked_regardless_of_tier():
    auditor = _user(Role.AUDITOR, approval_limit_usd=0.0)
    pending = _pending(PolicyTier.APPROVAL_REQUIRED, estimated_cost_usd=1.0)
    with pytest.raises(HTTPException) as exc:
        _authorize_decision(auditor, pending)
    assert exc.value.status_code == 403


def test_admin_approves_tier2_with_unlimited_authority():
    admin = _user(Role.ADMIN, approval_limit_usd=1_000_000_000.0)
    pending = _pending(PolicyTier.EXECUTIVE_APPROVAL, estimated_cost_usd=50_000_000.0)
    _authorize_decision(admin, pending)  # does not raise


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _start_incident(client, headers, line_id):
    body = {
        "plant_id": "FAC-P1",
        "line_id": line_id,
        "part_number": "P-1002",
        "vision_data": {"measured_bore_diameter_mm": 45.085},
        "priority": {
            "safety_impact": 0.9,
            "customer_impact": 0.6,
            "line_down_cost_per_hour_usd": 12000,
            "production_priority": 0.7,
            "is_systemic": False,
        },
    }
    resp = client.post("/incidents", json=body, headers=headers)
    assert resp.status_code == 200
    return resp.json()["incident_id"]


def test_low_limit_manager_gets_403_over_http(client):
    # End-to-end proof the unit-tested rule above actually applies through
    # the real endpoint, not just in isolation. The standard demo scenario
    # lands at Tier 1 with a $350 estimated cost (confirmed live this
    # session) - a manager with a lower limit must be refused.
    import asyncio

    low_limit_manager = _user(Role.MANAGER, approval_limit_usd=1.0)
    headers = {"Authorization": f"Bearer {create_access_token(low_limit_manager)}"}
    admin = _user(Role.ADMIN, approval_limit_usd=1_000_000_000.0)
    admin_headers = {"Authorization": f"Bearer {create_access_token(admin)}"}

    incident_id = _start_incident(client, admin_headers, line_id="Line-RBAC-Test-1")

    async def _wait_for_pending():
        for _ in range(200):
            resp = client.get("/approvals", headers=admin_headers)
            pending = next((p for p in resp.json() if p["incidentId"] == incident_id), None)
            if pending is not None:
                return pending
            await asyncio.sleep(0.01)
        raise AssertionError("orchestrator never reached AwaitingApproval")

    pending = asyncio.run(_wait_for_pending())
    assert pending["policyTier"] == 1

    resp = client.post(f"/incidents/{incident_id}/approve", headers=headers)
    assert resp.status_code == 403

    # Clean up: an admin approval so this incident doesn't stay pending and
    # hold its line's preemption lock for the rest of the suite.
    client.post(f"/incidents/{incident_id}/approve", headers=admin_headers)
