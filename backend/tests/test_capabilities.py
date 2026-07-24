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
