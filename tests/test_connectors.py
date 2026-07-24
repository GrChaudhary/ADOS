"""
ServiceNow/SAP connectors — no sandbox instance exists for this pass (see
integrations/README.md), so these test the request shape against
httpx.MockTransport rather than a live system: correct auth headers,
correct path/table resolution, and correct fallback behavior when
unconfigured. Real-instance verification is a follow-up once credentials
are available.
"""

import httpx
import pytest

from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from integrations.connectors.sap import SAPConnector
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.hub import IntegrationHub
from integrations.capability_registry import CapabilityRegistry
from integrations.connectors.console import ConsoleConnector
from integrations.policy_engine import ConnectorPolicyEngine


def _call(capability: Capability, **input_kwargs) -> CapabilityCall:
    return CapabilityCall(
        capability=capability,
        incident_id="inc-connector-test",
        requested_by="tests/test_connectors",
        input=input_kwargs,
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


@pytest.mark.asyncio
async def test_servicenow_not_configured_fails_clearly(monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    connector = ServiceNowConnector()
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))
    assert response.status == CallStatus.FAILED
    assert "not configured" in response.error


@pytest.mark.asyncio
async def test_servicenow_posts_to_correct_table_with_basic_auth(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://devinstance.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "admin")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "secret")

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth_header"] = request.headers.get("authorization")
        return httpx.Response(201, json={"result": {"sys_id": "abc123"}})

    connector = ServiceNowConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(
        _call(Capability.CREATE_CHANGE_REQUEST, short_description="Line 3 maintenance")
    )

    assert response.status == CallStatus.SUCCEEDED
    assert response.output == {"sys_id": "abc123"}
    assert "/api/now/table/change_request" in captured["url"]
    assert captured["auth_header"].startswith("Basic ")


@pytest.mark.asyncio
async def test_servicenow_surfaces_http_errors_as_failed(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://devinstance.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "admin")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    connector = ServiceNowConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="x"))
    assert response.status == CallStatus.FAILED
    assert "403" in response.error


@pytest.mark.asyncio
async def test_sap_not_configured_fails_clearly(monkeypatch):
    monkeypatch.delenv("SAP_BASE_URL", raising=False)
    connector = SAPConnector()
    response = await connector.execute(_call(Capability.CREATE_PURCHASE_ORDER))
    assert response.status == CallStatus.FAILED
    assert "not configured" in response.error


@pytest.mark.asyncio
async def test_sap_fetches_csrf_token_before_posting(monkeypatch):
    monkeypatch.setenv("SAP_BASE_URL", "https://sap-dev.example.com")
    monkeypatch.setenv("SAP_API_KEY", "test-api-key")

    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        if request.method == "GET":
            assert request.headers.get("x-csrf-token") == "fetch"
            return httpx.Response(200, headers={"x-csrf-token": "tok-123"})
        assert request.headers.get("x-csrf-token") == "tok-123"
        assert request.headers.get("apikey") == "test-api-key"
        return httpx.Response(201, json={"d": {"PurchaseOrder": "4500000123"}})

    connector = SAPConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_PURCHASE_ORDER, Supplier="S-201"))

    assert response.status == CallStatus.SUCCEEDED
    assert response.output == {"PurchaseOrder": "4500000123"}
    assert len(requests_seen) == 2  # CSRF fetch + POST


@pytest.mark.asyncio
async def test_policy_engine_prefers_configured_real_connector_over_console(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://devinstance.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "admin")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "secret")

    registry = CapabilityRegistry()
    registry.register(ServiceNowConnector())
    registry.register(ConsoleConnector())
    engine = ConnectorPolicyEngine(registry)

    selected = engine.select_connector(_call(Capability.CREATE_INCIDENT, short_description="x"))
    assert selected.name == "servicenow"


@pytest.mark.asyncio
async def test_policy_engine_falls_back_to_console_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)

    registry = CapabilityRegistry()
    registry.register(ServiceNowConnector())
    registry.register(ConsoleConnector())
    engine = ConnectorPolicyEngine(registry)

    selected = engine.select_connector(_call(Capability.CREATE_INCIDENT, short_description="x"))
    assert selected.name == "console"


@pytest.mark.asyncio
async def test_default_hub_still_resolves_notify_operator_to_console():
    hub = IntegrationHub()
    # mirror default_hub()'s registration order without needing env state
    hub.registry.register(ServiceNowConnector())
    hub.registry.register(SAPConnector())
    hub.registry.register(ConsoleConnector())

    response = await hub.invoke(_call(Capability.NOTIFY_OPERATOR, message="hello"))
    assert response.status == CallStatus.SUCCEEDED
    assert response.connector == "console"
