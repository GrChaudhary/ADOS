"""
Tests for SmartFactoryConnector — integrations/connectors/smart_factory.py.
"""

import pytest
import httpx
from contracts import Capability, CapabilityCall, CallStatus
from integrations.connectors.smart_factory import SmartFactoryConnector
from integrations.hub import default_hub


@pytest.mark.asyncio
async def test_smart_factory_connector_capabilities():
    """Verify SmartFactoryConnector handles all expected manufacturing capabilities."""
    connector = SmartFactoryConnector()
    assert Capability.REROUTE_STATION in connector.capabilities
    assert Capability.EVALUATE_GNN_RISK in connector.capabilities
    assert Capability.READ_RUL_TELEMETRY in connector.capabilities
    assert Capability.SORT_WORKPIECE in connector.capabilities
    assert Capability.UPDATE_MES in connector.capabilities
    assert Capability.RESERVE_INVENTORY in connector.capabilities


@pytest.mark.asyncio
async def test_smart_factory_connector_mocked_gateway():
    """Test execution against a mocked transport."""
    async def mock_handler(request: httpx.Request):
        url = str(request.url)
        if "/twin/gnn-risk" in url:
            return httpx.Response(200, json={"global_risk_score": 0.15, "status": "LOW_RISK"})
        elif "/twin/rul" in url:
            return httpx.Response(200, json={"machines": {"ov": {"rul_hours": 450}}})
        elif "/stations/vgr/action" in url:
            return httpx.Response(200, json={"status": "success", "action": "reroute", "station_id": "vgr"})
        return httpx.Response(400, json={"error": "unknown endpoint"})

    transport = httpx.MockTransport(mock_handler)
    connector = SmartFactoryConnector(transport=transport)

    # 1. GNN Risk
    call_gnn = CapabilityCall(
        request_id="req-gnn-1",
        capability=Capability.EVALUATE_GNN_RISK,
        input={},
    )
    res_gnn = await connector.execute(call_gnn)
    assert res_gnn.status == CallStatus.SUCCEEDED
    assert res_gnn.result["global_risk_score"] == 0.15

    # 2. RUL Telemetry
    call_rul = CapabilityCall(
        request_id="req-rul-1",
        capability=Capability.READ_RUL_TELEMETRY,
        input={},
    )
    res_rul = await connector.execute(call_rul)
    assert res_rul.status == CallStatus.SUCCEEDED
    assert res_rul.result["machines"]["ov"]["rul_hours"] == 450

    # 3. Reroute Station
    call_reroute = CapabilityCall(
        request_id="req-reroute-1",
        capability=Capability.REROUTE_STATION,
        input={"target": "Line_2_VGR"},
    )
    res_reroute = await connector.execute(call_reroute)
    assert res_reroute.status == CallStatus.SUCCEEDED
    assert res_reroute.result["station_id"] == "vgr"


@pytest.mark.asyncio
async def test_smart_factory_connector_registered_in_default_hub():
    """Verify SmartFactoryConnector is registered in default_hub."""
    hub = default_hub()
    connectors = [c.name for c in hub.registry._connectors]
    assert "smart_factory" in connectors
