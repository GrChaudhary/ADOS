def test_publish_and_list_events(client, auth_headers):
    envelope = {
        "eventType": "IncidentDetected",
        "correlationId": "inc-test-1",
        "producedBy": "backend/tests",
        "payload": {"plantId": "plant-1", "lineId": "line-3", "defectType": "dimensional"},
    }

    publish_resp = client.post("/events", json=envelope, headers=auth_headers)
    assert publish_resp.status_code == 200
    assert publish_resp.json()["correlationId"] == "inc-test-1"

    list_resp = client.get("/events", params={"correlation_id": "inc-test-1"}, headers=auth_headers)
    assert list_resp.status_code == 200
    events = list_resp.json()
    assert len(events) == 1
    assert events[0]["eventType"] == "IncidentDetected"


def test_events_requires_auth(client):
    response = client.get("/events")
    assert response.status_code == 401
