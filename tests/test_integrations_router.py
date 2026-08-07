"""
Unit & integration tests for the Integration Connector Status Router
(GET /integrations/status).

These replace the frontend's old hardcoded "Connected" badge with real
data - see frontend-next/src/app/integrations/page.tsx.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from conftest import admin_auth_header

AUTH = admin_auth_header()


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
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    monkeypatch.delenv("SERVICENOW_USERNAME", raising=False)
    monkeypatch.delenv("SERVICENOW_PASSWORD", raising=False)

    response = client.get("/integrations/status", headers=AUTH)
    assert response.status_code == 200
    by_id = {c["id"]: c for c in response.json()}

    # Card titles must be human-readable names, not raw connector ids.
    assert by_id["sap"]["name"] == "SAP S/4HANA ERP Connector"
    assert by_id["postgresql"]["name"] == "PostgreSQL"

    # No SAP_BASE_URL/SAP_API_KEY set -> honestly reported as unconfigured,
    # not "Connected".
    assert by_id["sap"]["connected"] is False

    # No SERVICENOW_* creds set -> not configured either.
    assert by_id["servicenow"]["connected"] is False

    # marketplace.py never makes a real HTTP call - it returns canned data -
    # so it's flagged "Simulated" rather than presented as a live system.
    assert "Simulated" in by_id["marketplace"]["status"]

    # Factory MES/PLC has no connector implementation at all (no OPC-UA/
    # Modbus client anywhere in the repo) - never reported connected.
    assert by_id["factory_mes"]["connected"] is False

    # Postgres reports its own real, live-checked state (required
    # application infrastructure — TestClient(app)'s lifespan already
    # fails startup if it's unreachable, so this is genuinely connected
    # in every test, not a fabricated number).
    assert by_id["postgresql"]["connected"] is True
