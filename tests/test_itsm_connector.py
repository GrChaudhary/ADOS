"""
WatsonxITSMConnector — like tests/test_connectors.py's ServiceNow/SAP
tests, this uses httpx.MockTransport rather than live network calls.

The original version of this file called the real IBM IAM token endpoint
on every test run (~12s per run, using the real WO_API_KEY) and asserted
on a fabricated "SUCCEEDED" response the connector returned even when the
real call failed — see integrations/connectors/watsonx_itsm.py's history.
Both are fixed: no live calls here, and the connector itself now reports
FAILED honestly instead of fabricating ticket data.
"""

import httpx
import pytest

from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from integrations import default_hub
from integrations.connectors.watsonx_itsm import WatsonxITSMConnector


def _call(capability: Capability, **input_kwargs) -> CapabilityCall:
    return CapabilityCall(
        capability=capability,
        incident_id="inc-itsm-test",
        requested_by="tests/test_itsm_connector",
        input=input_kwargs,
        governance=GovernanceInfo(policy_tier=PolicyTier.APPROVAL_REQUIRED, approved_by="usr_mfg_mgr"),
    )


def test_not_configured_without_explicit_opt_in(monkeypatch):
    # WO_INSTANCE/WO_API_KEY alone (the ADK CLI's own auth) must not be
    # enough — see is_configured()'s docstring for why.
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.delenv("WO_ITSM_INTEGRATION_ENABLED", raising=False)

    connector = WatsonxITSMConnector()
    assert connector.is_configured() is False


def test_configured_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_INTEGRATION_ENABLED", "true")

    connector = WatsonxITSMConnector()
    assert connector.is_configured() is True
    assert Capability.CREATE_INCIDENT in connector.capabilities


@pytest.mark.asyncio
async def test_iam_token_failure_reports_failed_not_fabricated_success(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "iam.cloud.ibm.com" in str(request.url)
        return httpx.Response(400, json={"error": "invalid apikey"})

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.FAILED
    assert "IAM token" in response.error


@pytest.mark.asyncio
async def test_itsm_endpoint_failure_reports_failed_not_fabricated_success(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        return httpx.Response(404, text="not found")

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.FAILED
    assert "404" in response.error


@pytest.mark.asyncio
async def test_success_path_passes_through_real_endpoint_output(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        assert request.headers.get("authorization") == "Bearer fake-iam-token"
        return httpx.Response(200, json={"result": {"ticket_id": "INC0012345"}})

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.SUCCEEDED
    assert response.output == {"ticket_id": "INC0012345"}


@pytest.mark.asyncio
async def test_default_hub_routes_to_console_when_itsm_not_opted_in(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.delenv("WO_ITSM_INTEGRATION_ENABLED", raising=False)
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    monkeypatch.delenv("SAP_BASE_URL", raising=False)

    hub = default_hub()
    response = await hub.invoke(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.SUCCEEDED
    assert response.connector == "console"
