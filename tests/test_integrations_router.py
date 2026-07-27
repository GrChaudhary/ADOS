"""
Unit & integration tests for the Integration Connector Status Router
(GET /integrations/status, POST /integrations/watsonx/test-connection).

These replace the frontend's old hardcoded "Connected" badge with real
data - see frontend-next/src/app/integrations/page.tsx.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

AUTH = {"Authorization": "Bearer dev-local-only-token"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_status_endpoint_unauthorized(client):
    response = client.get("/integrations/status")
    assert response.status_code == 401


def test_status_reports_real_configuration_state(client, monkeypatch):
    monkeypatch.delenv("SAP_BASE_URL", raising=False)
    monkeypatch.delenv("SAP_API_KEY", raising=False)
    monkeypatch.delenv("WO_ITSM_INTEGRATION_ENABLED", raising=False)
    monkeypatch.delenv("CLOUDANT_URL", raising=False)
    monkeypatch.delenv("CLOUDANT_API_KEY", raising=False)

    response = client.get("/integrations/status", headers=AUTH)
    assert response.status_code == 200
    by_id = {c["id"]: c for c in response.json()}

    # Card titles must be human-readable names, not raw connector ids.
    assert by_id["sap"]["name"] == "SAP S/4HANA ERP Connector"
    assert by_id["cloudant_nosql"]["name"] == "IBM Cloudant NoSQL Database"

    # No SAP_BASE_URL/SAP_API_KEY set -> honestly reported as unconfigured,
    # not "Connected".
    assert by_id["sap"]["connected"] is False

    # WO_ITSM_INTEGRATION_ENABLED not set -> not configured either, even if
    # WO_INSTANCE/WO_API_KEY happen to be present in the environment.
    assert by_id["watsonx_itsm"]["connected"] is False

    # marketplace.py never makes a real HTTP call - it returns canned data -
    # so it's flagged "Simulated" rather than presented as a live system.
    assert "Simulated" in by_id["marketplace"]["status"]

    # Factory MES/PLC has no connector implementation at all (no OPC-UA/
    # Modbus client anywhere in the repo) - never reported connected.
    assert by_id["factory_mes"]["connected"] is False

    # Cloudant reports its own real (unconfigured-in-tests) state, not a
    # fabricated number.
    assert by_id["cloudant_nosql"]["connected"] is False


def test_watsonx_test_connection_fails_clearly_without_credentials(client, monkeypatch):
    monkeypatch.delenv("WO_INSTANCE", raising=False)
    monkeypatch.delenv("WO_API_KEY", raising=False)

    response = client.post("/integrations/watsonx/test-connection", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert "not set" in body["error"]


def test_watsonx_test_connection_surfaces_connector_result(client, monkeypatch):
    from integrations.connectors.watsonx_itsm import WatsonxITSMConnector

    async def fake_test_connection(self):
        return {"connected": True, "agent_count": 1, "agents": ["ados_executive_copilot"]}

    monkeypatch.setattr(WatsonxITSMConnector, "test_connection", fake_test_connection)

    response = client.post("/integrations/watsonx/test-connection", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    assert body["agentCount"] == 1
    assert body["agents"] == ["ados_executive_copilot"]
