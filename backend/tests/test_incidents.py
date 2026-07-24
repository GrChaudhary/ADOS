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

    approve_resp = client.post(
        f"/incidents/{incident_id}/approve", json={"approved_by": "ops-lead-api"}, headers=auth_headers
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
    assert record["finalState"] == "Resolved"
    assert record["approvedBy"] == "ops-lead-api"


def test_incidents_requires_auth(client):
    response = client.get("/incidents")
    assert response.status_code == 401
