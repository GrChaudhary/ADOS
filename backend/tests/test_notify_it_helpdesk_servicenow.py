"""
SAFE, DEFAULT tests for NotifyITHelpdesk -> ServiceNow.

Deterministic, repeatable, and **no external writes**: every request goes to an
`httpx.MockTransport`, so this exercises the real connector code — auth header,
Table API path, field translation, response parsing, error handling — without
touching anyone's instance.

The test that genuinely creates a ServiceNow incident lives in
`test_servicenow_external.py` and is marked `external`, deselected by default.
"""

import base64
import json

import httpx
import pytest

from contracts import CallStatus, Capability, CapabilityCall, CapabilityResponse, GovernanceInfo, PolicyTier
from integrations.connectors.servicenow import _CAPABILITY_TABLE, ServiceNowConnector
from integrations.connectors.servicenow_fields import build_record
from integrations.hub import default_hub

MISSION_ID = "b2ca8fca-a9c1-438a-b4ae-4254bef36e46"


@pytest.fixture(autouse=True)
def _servicenow_env(monkeypatch):
    """Fake credentials. The MockTransport intercepts before any socket opens,
    so these never reach a network."""
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://example.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "ados-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "not-a-real-password")


def _call(**input_) -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.NOTIFY_IT_HELPDESK,
        input=input_,
        requested_by=f"prime-runtime:mission:{MISSION_ID}",
        incident_id=MISSION_ID,
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


def _recording_transport(status=201, payload=None):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content or b"{}")
        return httpx.Response(
            status,
            json=payload if payload is not None else {
                "result": {"sys_id": "0123456789abcdef", "number": "INC0012345",
                           "short_description": seen["body"].get("short_description")}
            },
        )

    return httpx.MockTransport(handler), seen


# --- routing -----------------------------------------------------------------

def test_notify_it_helpdesk_maps_to_the_incident_table():
    assert _CAPABILITY_TABLE[Capability.NOTIFY_IT_HELPDESK] == "incident"


def test_servicenow_beats_console_for_notify_it_helpdesk():
    """Before this change the capability had no real connector and Console —
    which declares set(Capability) — returned "[console] simulated
    NotifyITHelpdesk". That was the acceptance run's one simulated step."""
    names = [c.name for c in default_hub().registry.connectors_for(Capability.NOTIFY_IT_HELPDESK)]
    assert "servicenow" in names
    assert names.index("servicenow") < names.index("console")


def test_notify_manager_deliberately_stays_on_console():
    """The contrast is the point: NotifyManager is a person-to-person message
    with no ticket semantics, and routing it to ServiceNow just to make it hit
    something real would dress up a gap."""
    assert Capability.NOTIFY_MANAGER not in _CAPABILITY_TABLE


# --- field translation -------------------------------------------------------

def test_the_agents_summary_becomes_the_short_description():
    """The runtime calls run_capability('NotifyITHelpdesk', {'summary': ...}).
    That is not ServiceNow's vocabulary, and posting it raw would create a
    blank ticket that still returns 201."""
    record = build_record(
        Capability.NOTIFY_IT_HELPDESK,
        {"summary": "Root cause: DB pool size raised 10->100 in release 2026.8.9-rc3"},
        {"mission_id": MISSION_ID, "request_id": "req-1", "requested_by": "prime-runtime"},
    )
    assert record["short_description"].startswith("Root cause: DB pool size")
    assert "short_description" in record and record["short_description"]


def test_provenance_is_written_into_the_ticket():
    """An operator opening this at 3am must be able to see what raised it.
    Without provenance an autonomously-created ticket is a mystery."""
    record = build_record(
        Capability.NOTIFY_IT_HELPDESK, {"summary": "pool exhaustion"},
        {"mission_id": MISSION_ID, "request_id": "req-42", "requested_by": "prime-runtime:mission:x"},
    )
    assert MISSION_ID in record["description"]
    assert "req-42" in record["description"]
    assert "ADOS" in record["description"]


def test_a_long_summary_is_truncated_for_short_description_but_kept_in_full():
    """short_description is a 160-char column and ServiceNow truncates silently,
    so a root-cause sentence would lose its ending with no error."""
    long_summary = "x" * 400
    record = build_record(Capability.NOTIFY_IT_HELPDESK, {"summary": long_summary}, {})
    assert len(record["short_description"]) <= 160
    assert long_summary in record["description"]


def test_an_empty_summary_still_produces_an_actionable_ticket():
    record = build_record(Capability.NOTIFY_IT_HELPDESK, {}, {})
    assert record["short_description"].strip()
    assert "no summary supplied" in record["short_description"]


def test_a_servicenow_shaped_caller_is_still_passed_through():
    """itsm_agent.py already speaks ServiceNow and must keep working."""
    record = build_record(
        Capability.NOTIFY_IT_HELPDESK,
        {"short_description": "already shaped", "description": "d", "action": "internal"},
        {},
    )
    assert record["short_description"] == "already shaped"
    assert "action" not in record


# --- the wire ----------------------------------------------------------------

async def test_the_request_is_a_post_to_the_incident_table_with_basic_auth():
    transport, seen = _recording_transport()
    response = await ServiceNowConnector(transport=transport).execute(
        _call(summary="Root cause: connection pool exhaustion")
    )

    assert response.status is CallStatus.SUCCEEDED
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/now/table/incident"
    expected = base64.b64encode(b"ados-test:not-a-real-password").decode()
    assert seen["auth"] == f"Basic {expected}"
    assert seen["body"]["short_description"].startswith("Root cause")


async def test_sys_id_and_number_come_back_in_the_output():
    """These are the identifiers the external test verifies against. If the
    connector loses them, there is nothing to cross-check a real record with."""
    transport, _ = _recording_transport()
    response = await ServiceNowConnector(transport=transport).execute(_call(summary="s"))

    assert response.output["sys_id"] == "0123456789abcdef"
    assert response.output["number"] == "INC0012345"


async def test_a_4xx_is_a_failure_not_a_success():
    transport, _ = _recording_transport(status=403, payload={"error": {"message": "forbidden"}})
    response = await ServiceNowConnector(transport=transport).execute(_call(summary="s"))

    assert response.status is CallStatus.FAILED
    assert "403" in (response.error or "")


async def test_a_transport_error_that_never_reached_the_server_is_a_failure_not_a_success():
    """P9: `ConnectError` means the request never left this process — nothing
    could have happened out there, so FAILED (safe to retry) is correct. See
    the sibling test below for the opposite case: an error that could mean
    the request DID reach the server."""
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    response = await ServiceNowConnector(transport=httpx.MockTransport(boom)).execute(
        _call(summary="s")
    )
    assert response.status is CallStatus.FAILED
    assert "never reached" in (response.error or "")


async def test_a_transport_error_that_may_have_reached_the_server_is_unknown_not_failed():
    """P9: unlike ConnectError above, a read timeout can happen AFTER the
    POST has already left this process — ServiceNow's Table API has no
    idempotency mechanism, so treating this as an ordinary FAILED (implying
    "safe to retry") would risk a real duplicate record. See
    integrations/connectors/servicenow.py's own docstring and
    orchestrate/runtime/capability_reconcile.py for the recovery path."""
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out waiting for a response", request=request)

    response = await ServiceNowConnector(transport=httpx.MockTransport(boom)).execute(
        _call(summary="s")
    )
    assert response.status is CallStatus.UNKNOWN
    assert "may have already reached" in (response.error or "")


async def test_missing_credentials_fail_rather_than_pretend(monkeypatch):
    """The connector must never report success it did not achieve. Note this is
    the CONNECTOR's behaviour; connector *selection* may still fall back to
    Console, which is why the external test asserts connector == 'servicenow'
    rather than trusting that a call succeeded."""
    monkeypatch.delenv("SERVICENOW_INSTANCE_URL", raising=False)
    response = await ServiceNowConnector().execute(_call(summary="s"))

    assert response.status is CallStatus.FAILED
    assert "not configured" in (response.error or "")


async def test_resolve_record_patches_the_record(monkeypatch):
    """Cleanup for the external test. Closing, not deleting: closing is the
    normal ServiceNow lifecycle and preserves the audit trail the test exists
    to produce."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content or b"{}")
        return httpx.Response(200, json={"result": {"state": "7"}})

    ok, detail = await ServiceNowConnector(transport=httpx.MockTransport(handler)).resolve_record(
        "incident", "abc123", close_notes="ADOS integration test cleanup"
    )
    assert ok and detail == "7"
    assert seen["method"] == "PATCH"
    assert seen["path"] == "/api/now/table/incident/abc123"
    assert seen["body"]["state"] == "7"
    assert "close_notes" in seen["body"]


async def test_fetch_record_reads_a_record_back():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"result": {"sys_id": "abc123", "number": "INC1"}})

    ok, record = await ServiceNowConnector(transport=httpx.MockTransport(handler)).fetch_record(
        "incident", "abc123"
    )
    assert ok and record["number"] == "INC1"
