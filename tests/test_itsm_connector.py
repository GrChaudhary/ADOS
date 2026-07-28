"""
WatsonxITSMConnector — like tests/test_connectors.py's ServiceNow/SAP
tests, this uses httpx.MockTransport rather than live network calls.

The original version of this file called the real IBM IAM token endpoint
on every test run (~12s per run, using the real WO_API_KEY) and asserted
on a fabricated "SUCCEEDED" response the connector returned even when the
real call failed — see integrations/connectors/watsonx_itsm.py's history.
Both are fixed: no live calls here, and the connector itself reports
FAILED honestly instead of fabricating ticket data.

This version also covers the two-flag safety gate
(WO_ITSM_INTEGRATION_ENABLED vs WO_ITSM_LIVE_WRITES_ENABLED) added when
execute() was rewired from a fake /v1/agents/itsm/run endpoint to the
real, live-verified /v1/orchestrate/{agent_id}/chat/completions endpoint
against the tenant's actual ServiceNow toolkit agents.
"""

import json

import httpx
import pytest

from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from integrations import default_hub
from integrations.connectors.watsonx_itsm import WatsonxITSMConnector, _INCIDENT_AGENT_ID


def _call(capability: Capability, policy_tier: PolicyTier = PolicyTier.APPROVAL_REQUIRED, **input_kwargs) -> CapabilityCall:
    return CapabilityCall(
        capability=capability,
        incident_id="inc-itsm-test",
        requested_by="tests/test_itsm_connector",
        input=input_kwargs,
        governance=GovernanceInfo(policy_tier=policy_tier, approved_by="usr_mfg_mgr"),
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


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
async def test_execute_blocked_when_live_writes_not_enabled(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.delenv("WO_ITSM_LIVE_WRITES_ENABLED", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network call should be made when live writes are disabled")

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.FAILED
    assert "WO_ITSM_LIVE_WRITES_ENABLED" in response.error


@pytest.mark.asyncio
async def test_iam_token_failure_reports_failed_not_fabricated_success(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "iam.cloud.ibm.com" in str(request.url)
        return httpx.Response(400, json={"error": "invalid apikey"})

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.FAILED
    assert "IAM token" in response.error


@pytest.mark.asyncio
async def test_chat_completions_endpoint_failure_reports_failed(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        return httpx.Response(404, text="not found")

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.FAILED
    assert "404" in response.error
    assert any(f"/v1/orchestrate/{_INCIDENT_AGENT_ID}/chat/completions" in u for u in seen_urls)


@pytest.mark.asyncio
async def test_success_path_parses_structured_result_trailer(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    reply = (
        "I've created the incident.\n"
        'RESULT: {"status": "created", "ticket_id": "INC0012345", "reason": null}'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        assert request.headers.get("authorization") == "Bearer fake-iam-token"
        return _chat_response(reply)

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.SUCCEEDED
    assert response.output["ticket_id"] == "INC0012345"


@pytest.mark.asyncio
async def test_success_path_parses_streamed_sse_response(monkeypatch):
    # The real endpoint sometimes returns text/event-stream (a sequence of
    # `data: {...}` lines) instead of a single JSON object, even without
    # `stream: true` in the request — observed live this session. Only the
    # final line carries the full text in choices[0].message.content;
    # earlier lines carry partial choices[0].delta.content chunks that
    # must not be mistaken for the complete reply.
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    full_reply = 'Created it.\nRESULT: {"status": "created", "ticket_id": "INC0099999", "reason": null}'
    sse_body = (
        'data: {"object": "thread.message.delta", "choices": [{"delta": {"content": "Cre"}}]}\n'
        "\n"
        'data: {"object": "thread.message.delta", "choices": [{"delta": {"content": "ated"}}]}\n'
        "\n"
        f'data: {{"object": "thread.message.completed", "choices": [{{"message": {{"role": "assistant", "content": {json.dumps(full_reply)}}}}}]}}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        return httpx.Response(200, text=sse_body, headers={"content-type": "text/event-stream"})

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.SUCCEEDED
    assert response.output["ticket_id"] == "INC0099999"


@pytest.mark.asyncio
async def test_agent_reports_failure_via_structured_result(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    reply = 'RESULT: {"status": "failed", "ticket_id": null, "reason": "missing assignment group"}'

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        return _chat_response(reply)

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.FAILED
    assert "missing assignment group" in response.error


@pytest.mark.asyncio
async def test_missing_structured_result_treated_as_failed_not_fabricated(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    # Simulates the agent asking a clarifying question instead of acting.
    reply = "Which assignment group should I use for this incident?"

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        return _chat_response(reply)

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.status == CallStatus.FAILED
    assert "clarifying question" in response.error


@pytest.mark.asyncio
async def test_short_description_derived_from_execution_steps_when_not_provided(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    captured_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        captured_body.update(json.loads(request.content))
        return _chat_response('RESULT: {"status": "created", "ticket_id": "INC1", "reason": null}')

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    call = _call(
        Capability.CREATE_INCIDENT,
        execution_steps=["1. Send CNC parameter adjustment (tool_offset_z_mm = -0.035mm) to Line 2 PLC"],
        target_line_id="Line 2",
    )
    await connector.execute(call)

    prompt = captured_body["messages"][0]["content"]
    short_description_line = next(line for line in prompt.splitlines() if line.startswith("short_description:"))
    assert "Send CNC parameter adjustment" in short_description_line
    assert "1. Send CNC" not in short_description_line  # numbering prefix stripped from short_description specifically


@pytest.mark.asyncio
async def test_impact_urgency_derived_from_policy_tier(monkeypatch):
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_LIVE_WRITES_ENABLED", "true")

    captured_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "iam.cloud.ibm.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "fake-iam-token"})
        captured_bodies.append(json.loads(request.content))
        return _chat_response('RESULT: {"status": "created", "ticket_id": "INC1", "reason": null}')

    connector = WatsonxITSMConnector(transport=httpx.MockTransport(handler))
    await connector.execute(_call(Capability.CREATE_INCIDENT, policy_tier=PolicyTier.AUTONOMOUS, short_description="x"))
    await connector.execute(_call(Capability.CREATE_INCIDENT, policy_tier=PolicyTier.EXECUTIVE_APPROVAL, short_description="x"))

    autonomous_prompt = captured_bodies[0]["messages"][0]["content"]
    executive_prompt = captured_bodies[1]["messages"][0]["content"]
    assert "3 - Low" in autonomous_prompt
    assert "1 - High" in executive_prompt


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


@pytest.mark.asyncio
async def test_default_hub_routes_to_watsonx_but_stays_safed_without_live_writes_flag(monkeypatch):
    # Regression guard: WO_ITSM_INTEGRATION_ENABLED alone (connector
    # eligible/selected) must never be enough to produce a real write —
    # WO_ITSM_LIVE_WRITES_ENABLED is required too.
    monkeypatch.setenv("WO_INSTANCE", "https://api.example.watson-orchestrate.cloud.ibm.com/instances/x")
    monkeypatch.setenv("WO_API_KEY", "test-key")
    monkeypatch.setenv("WO_ITSM_INTEGRATION_ENABLED", "true")
    monkeypatch.delenv("WO_ITSM_LIVE_WRITES_ENABLED", raising=False)

    hub = default_hub()
    response = await hub.invoke(_call(Capability.CREATE_INCIDENT, short_description="test"))

    assert response.connector == "watsonx_itsm"
    assert response.status == CallStatus.FAILED
    assert "WO_ITSM_LIVE_WRITES_ENABLED" in response.error
