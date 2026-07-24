"""
Integration test for GET /executive/incidents/{incident_id}/options — Phase 3's
Option A/B/C comparison, wired against real live incidents (not seed fixtures),
matching every other /executive/* route's convention (see
backend/app/routers/executive.py's _records() docstring).
"""

import asyncio

import pytest

from backend.tests.test_incidents import _start_incident


def test_incident_options_requires_auth(client):
    response = client.get("/executive/incidents/INC-DOES-NOT-EXIST/options")
    assert response.status_code == 401


def test_incident_options_unknown_incident_404(client, auth_headers):
    response = client.get("/executive/incidents/INC-DOES-NOT-EXIST/options", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_incident_options_reflects_live_orchestrator_run(client, auth_headers):
    incident_id = _start_incident(client, auth_headers, line_id="Line-Options-1")

    # Tier 1 by construction (see orchestrate/governance.py) — wait for the
    # orchestrator to enqueue a pending approval, then approve it, same as
    # backend/tests/test_incidents.py::test_incident_lifecycle_via_api.
    pending = None
    for _ in range(200):
        resp = client.get("/approvals", headers=auth_headers)
        pending = next((p for p in resp.json() if p["incidentId"] == incident_id), None)
        if pending is not None:
            break
        await asyncio.sleep(0.01)
    assert pending is not None, "orchestrator never reached AwaitingApproval"

    approve_resp = client.post(
        f"/incidents/{incident_id}/approve", json={"approved_by": "ops-lead-options-test"}, headers=auth_headers
    )
    assert approve_resp.status_code == 200

    record = None
    for _ in range(200):
        resp = client.get(f"/incidents/{incident_id}", headers=auth_headers)
        body = resp.json()
        if body.get("finalState") in ("Resolved", "Failed"):
            record = body
            break
        await asyncio.sleep(0.01)
    assert record is not None, "incident never reached a terminal state"

    resp = client.get(f"/executive/incidents/{incident_id}/options", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["incidentId"] == incident_id
    assert len(data["options"]) >= 1
    assert data["options"][0]["isRecommended"] is True
    assert data["options"][0]["letter"] == "A"
