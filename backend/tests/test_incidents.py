import asyncio

import pytest


def _start_incident(client, auth_headers, line_id="Line3"):
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
    response = client.post("/incidents", json=body, headers=auth_headers)
    assert response.status_code == 200
    return response.json()["incident_id"]


@pytest.mark.asyncio
async def test_incident_lifecycle_via_api(client, auth_headers):
    incident_id = _start_incident(client, auth_headers, line_id="Line-API-1")

    # Poll until the orchestrator reaches AwaitingApproval and enqueues a
    # pending approval for this incident (Tier 1 by construction — see
    # orchestrate/governance.py's confidence thresholds).
    pending = None
    for _ in range(200):
        resp = client.get("/approvals", headers=auth_headers)
        pending = next((p for p in resp.json() if p["incidentId"] == incident_id), None)
        if pending is not None:
            break
        await asyncio.sleep(0.01)
    assert pending is not None, "orchestrator never reached AwaitingApproval"

    status_resp = client.get(f"/incidents/{incident_id}", headers=auth_headers)
    assert status_resp.json()["status"] == "in_progress"

    # approved_by is no longer client-supplied (backend/app/rbac.py) - it's
    # derived from the authenticated session, so no request body at all.
    approve_resp = client.post(f"/incidents/{incident_id}/approve", headers=auth_headers)
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
    assert record["finalState"] == "Resolved"
    # The synthetic test-admin identity from the auth_headers fixture
    # (backend/tests/conftest.py), not a client-supplied string.
    assert record["approvedBy"] == "Test Admin (admin)"


def test_incidents_requires_auth(client):
    response = client.get("/incidents")
    assert response.status_code == 401


def test_briefing_audio_404_when_tts_not_enabled(client, auth_headers):
    # TTS_INCIDENT_BRIEFING_ENABLED is unset in the test process, so no
    # incident ever gets a cached briefing (orchestrate/orchestrator.py).
    incident_id = _start_incident(client, auth_headers, line_id="Line-Briefing-1")
    response = client.get(f"/incidents/{incident_id}/briefing-audio", headers=auth_headers)
    assert response.status_code == 404
