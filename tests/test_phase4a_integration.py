"""
Integration tests for Phase 4A:
- Decision Memory REST API (/memory/search, /memory/records/{id})
- External Marketplace Connector (QueryExternalStock, CreateExternalPO, GetFreightQuote)
- Governance Policy Tier Promotion Infrastructure
"""

import sys
from pathlib import Path
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from contracts import Capability, CapabilityCall, GovernanceInfo, PolicyTier, CallStatus, DecisionMemoryQuery
from integrations import default_hub
from orchestrate.governance import assign_policy_tier, promote_policy_tier, CAPABILITY_RISK_CLASS
from conftest import admin_auth_header  # sys.path already includes repo root, see above


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update(admin_auth_header())
        yield c


# --- 1. Decision Memory REST API Tests ---

def test_memory_search_api(client):
    query_payload = {
        "defectType": "dimensional fault",
        "plantId": "FAC-P1-L3",
        "limit": 5
    }
    resp = client.post("/memory/search", json=query_payload)

    assert resp.status_code == 200
    data = resp.json()
    assert "totalMatches" in data
    assert "records" in data
    assert data["totalMatches"] > 0
    assert len(data["records"]) > 0


def test_memory_get_record_by_id(client):
    target_id = "INC-2026-0701-001"
    resp = client.get(f"/memory/records/{target_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["incidentId"] == target_id
    assert data["plantId"] == "FAC-P04-L2"


def test_memory_get_record_not_found(client):
    resp = client.get("/memory/records/NONEXISTENT-ID")
    assert resp.status_code == 404


# --- 2. External Marketplace Connector Tests ---

@pytest.mark.asyncio
async def test_marketplace_connector_query_stock():
    hub = default_hub()
    call = CapabilityCall(
        capability=Capability.QUERY_EXTERNAL_STOCK,
        requestId="REQ-MKT-001",
        incidentId="INC-TEST-9001",
        requestedBy="agent",
        input={"part_number": "P-1002"},
        governance=GovernanceInfo(policyTier=PolicyTier.AUTONOMOUS)
    )

    resp = await hub.invoke(call)

    assert resp.status == CallStatus.SUCCEEDED
    assert resp.connector == "marketplace"
    assert resp.output["part_number"] == "P-1002"
    assert resp.output["available_stock"] > 0


@pytest.mark.asyncio
async def test_marketplace_connector_freight_quote():
    hub = default_hub()
    call = CapabilityCall(
        capability=Capability.GET_FREIGHT_QUOTE,
        requestId="REQ-MKT-002",
        incidentId="INC-TEST-9002",
        requestedBy="agent",
        input={"plant_id": "FAC-P1-L3"},
        governance=GovernanceInfo(policyTier=PolicyTier.AUTONOMOUS)
    )

    resp = await hub.invoke(call)

    assert resp.status == CallStatus.SUCCEEDED
    assert resp.connector == "marketplace"
    assert "carrier" in resp.output
    assert resp.output["estimated_cost_usd"] > 0


# --- 3. Governance Policy Tier Promotion Infrastructure Tests ---

def test_governance_policy_tier_promotion():
    cap = Capability.CREATE_EXTERNAL_PO
    assert CAPABILITY_RISK_CLASS[cap] == "high"
    # Still "high"/critical here, so any cost forces Tier 2 regardless.
    assert assign_policy_tier(cap, 0.99, estimated_cost_usd=5_000) == PolicyTier.EXECUTIVE_APPROVAL

    # Promote capability from high to medium risk class
    promote_policy_tier(cap, "medium")

    assert CAPABILITY_RISK_CLASS[cap] == "medium"
    # No longer critical, but cost still gates Tier 0 independent of the
    # risk-class promotion — must also be under the $25k low-exposure band.
    assert assign_policy_tier(cap, 0.98, estimated_cost_usd=10_000) == PolicyTier.AUTONOMOUS
