"""
ServiceNow field mapping (integrations/connectors/servicenow_fields.py) and
the HR offboarding routing that depends on it.

The bug these pin down: the connector used to POST CapabilityCall.input
straight to the Table API. ServiceNow ignores unknown fields and still
returns 201, so an MOA offboarding -- whose input is
{"employee_name": ..., "action": ...}, none of which are ServiceNow
columns -- would have created a blank ticket and recorded SUCCEEDED in the
audit trail. A silent wrong-success is worse than a failure, so these tests
assert on the actual posted body, not just the status code.
"""

import httpx
import pytest

from contracts import Capability, CallStatus, CapabilityCall, GovernanceInfo, PolicyTier
from integrations.connectors.servicenow import ServiceNowConnector
from integrations.connectors.servicenow_fields import build_record


def _call(capability: Capability, **input_kwargs) -> CapabilityCall:
    return CapabilityCall(
        capability=capability,
        incident_id="inc-servicenow-fields-test",
        requested_by="tests/test_servicenow_fields",
        input=input_kwargs,
        governance=GovernanceInfo(policy_tier=PolicyTier.AUTONOMOUS),
    )


# --------------------------------------------------------------------------
# The mapping itself — pure, no network
# --------------------------------------------------------------------------

def test_an_moa_offboarding_action_becomes_a_real_readable_ticket():
    """The exact payload orchestrate/moa/graph.py:_action_input() produces."""
    record = build_record(
        Capability.STOP_PAYROLL,
        {"employee_name": "Jane Doe", "action": "stop_payroll"},
    )

    assert "Jane Doe" in record["short_description"]
    assert "payroll" in record["short_description"].lower()
    # A human has to act on this ticket, so it needs prose, not a dict dump.
    assert "Jane Doe" in record["description"]
    assert record["urgency"] == "2"


@pytest.mark.parametrize(
    "capability",
    [
        Capability.REVOKE_BUILDING_ACCESS,
        Capability.DISABLE_IT_ACCESS,
        Capability.STOP_PAYROLL,
    ],
)
def test_every_hr_offboarding_action_names_the_employee_and_the_action(capability):
    record = build_record(capability, {"employee_name": "Sam Patel", "action": "x"})
    assert "Sam Patel" in record["short_description"]
    assert record["short_description"] != ""
    assert record["description"] != ""


def test_ados_internal_keys_never_reach_servicenow():
    """employee_name/action/capability_id are ADOS bookkeeping, not columns.
    Posting them is harmless (ServiceNow drops them) but it means the real
    information they carry is lost, which is how the blank-ticket bug
    happened in the first place."""
    record = build_record(
        Capability.DISABLE_IT_ACCESS,
        {"employee_name": "Jane Doe", "action": "disable_it_access", "capability_id": "abc"},
    )
    assert "employee_name" not in record
    assert "action" not in record
    assert "capability_id" not in record


def test_a_caller_already_speaking_servicenow_is_passed_through_untouched():
    """orchestrate/langgraph_agents/itsm_agent.py has always sent real field
    names. That path must keep working exactly as before."""
    record = build_record(
        Capability.CREATE_INCIDENT,
        {"short_description": "Printer on fire", "description": "The whole thing"},
    )
    assert record == {"short_description": "Printer on fire", "description": "The whole thing"}


def test_passthrough_still_strips_internal_keys():
    record = build_record(
        Capability.CREATE_INCIDENT,
        {"short_description": "Real one", "action": "create_incident"},
    )
    assert record == {"short_description": "Real one"}


def test_an_unmapped_capability_says_so_in_the_ticket_instead_of_going_blank():
    """The failure mode that matters: never post something that reads as
    empty to whoever opens it in ServiceNow."""
    record = build_record(Capability.CREATE_CHANGE_REQUEST, {"employee_name": "Jane Doe"})
    assert record["short_description"]
    assert "CreateChangeRequest" in record["short_description"]
    assert "no servicenow field mapping is defined" in record["description"].lower()


def test_a_missing_employee_name_does_not_produce_the_string_none():
    record = build_record(Capability.STOP_PAYROLL, {"action": "stop_payroll"})
    assert "None" not in record["short_description"]
    assert "unnamed employee" in record["short_description"]


# --------------------------------------------------------------------------
# Routing + the real posted body, through the connector
# --------------------------------------------------------------------------

@pytest.fixture
def servicenow_env(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://dev00000.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "admin")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "hunter2")


def test_hr_offboarding_actions_are_fulfilled_by_servicenow_at_all():
    """Before this change the three state-changing HR actions had no
    connector but Console, so an offboarding could never touch a real
    system no matter how ServiceNow was configured."""
    capabilities = ServiceNowConnector().capabilities
    assert Capability.REVOKE_BUILDING_ACCESS in capabilities
    assert Capability.DISABLE_IT_ACCESS in capabilities
    assert Capability.STOP_PAYROLL in capabilities


def test_notify_manager_is_deliberately_not_a_servicenow_ticket():
    """It is a notification, and no mail connector exists. Routing it here
    just to make it 'hit something real' would dress up a gap."""
    assert Capability.NOTIFY_MANAGER not in ServiceNowConnector().capabilities


@pytest.mark.asyncio
async def test_the_body_actually_posted_for_an_offboarding_is_a_real_record(servicenow_env):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={"result": {"sys_id": "abc123", "number": "CHG0012345"}})

    connector = ServiceNowConnector(transport=httpx.MockTransport(handler))
    response = await connector.execute(
        _call(Capability.STOP_PAYROLL, employee_name="Jane Doe", action="stop_payroll")
    )

    assert response.status == CallStatus.SUCCEEDED
    assert response.output["number"] == "CHG0012345"
    assert "/api/now/table/change_request" in captured["url"]
    # The whole point: a real description reached ServiceNow, and the ADOS
    # bookkeeping key did not.
    assert "Jane Doe" in captured["body"]
    assert "short_description" in captured["body"]
    assert "employee_name" not in captured["body"]


# --------------------------------------------------------------------------
# Canonical request-id provenance on the passthrough path
#
# Found by the P6-B live approval run, not by a unit test: CHG0030499 was
# created by a real Tier 2 human-approved capability and carried NO way back
# to the capability_requests row that authorized it. build_record() returned
# _passthrough(call_input) as soon as short_description was present — which
# CreateChangeRequest always sets — and that early return dropped `context`
# on the floor. NotifyITHelpdesk had provenance all along (INC0010028, P6-A),
# which is exactly why the gap went unnoticed.
#
# The invariant these pin down is one of the acceptance semantics: a
# provenance id printed on an external record must resolve back to the
# canonical ADOS request.
# --------------------------------------------------------------------------

_CTX = {
    "mission_id": "d00ff47c-6c1a-46d0-802f-e4f4ed3d4b96",
    "request_id": "01dcf9c3-0cb4-4954-bf79-b9bb6c4b8e01",
    "requested_by": "prime-runtime:mission:d00ff47c",
}


def test_a_change_request_carries_the_canonical_request_id():
    """The exact shape CreateChangeRequest sends: caller-supplied
    short_description, which used to bypass provenance entirely."""
    record = build_record(
        Capability.CREATE_CHANGE_REQUEST,
        {"short_description": "Restore DB_POOL_SIZE", "description": "Mission prose."},
        _CTX,
    )
    assert _CTX["request_id"] in record["description"]
    assert _CTX["mission_id"] in record["description"]
    assert _CTX["requested_by"] in record["description"]
    # The caller's own prose survives; provenance is appended, not substituted.
    assert "Mission prose." in record["description"]


def test_provenance_is_appended_when_the_caller_sent_no_description():
    record = build_record(
        Capability.CREATE_CHANGE_REQUEST, {"short_description": "No prose"}, _CTX
    )
    assert _CTX["request_id"] in record["description"]
    assert not record["description"].startswith("\n")


def test_a_record_that_already_names_its_request_id_is_not_stamped_twice():
    """A retry must not stack duplicate provenance blocks."""
    record = build_record(
        Capability.CREATE_CHANGE_REQUEST,
        {"short_description": "x", "description": f"Capability request: {_CTX['request_id']}"},
        _CTX,
    )
    assert record["description"].count(_CTX["request_id"]) == 1


def test_passthrough_without_context_is_still_byte_identical():
    """NEGATIVE CONTROL for the fix itself. itsm_agent.py calls build_record
    with no context at all; padding its record with 'Capability request:
    unknown' would be noise, not provenance. This is what keeps the fix from
    quietly rewriting an unrelated caller's ticket."""
    record = build_record(
        Capability.CREATE_INCIDENT,
        {"short_description": "Printer on fire", "description": "The whole thing"},
    )
    assert record == {"short_description": "Printer on fire", "description": "The whole thing"}


def test_partial_context_names_only_what_resolves():
    record = build_record(
        Capability.CREATE_CHANGE_REQUEST,
        {"short_description": "x"},
        {"mission_id": "m-1"},
    )
    assert "Mission: m-1" in record["description"]
    assert "unknown" not in record["description"]
    assert "Capability request:" not in record["description"]


@pytest.mark.asyncio
async def test_the_request_id_reaches_servicenow_in_the_posted_body(servicenow_env):
    """End of the chain, asserted on the wire: the id ADOS assigns to the
    capability request is in the body actually POSTed, not merely in the dict
    build_record returned."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={"result": {"sys_id": "s1", "number": "CHG0099999"}})

    connector = ServiceNowConnector(transport=httpx.MockTransport(handler))
    call = _call(Capability.CREATE_CHANGE_REQUEST, short_description="Restore pool size")
    response = await connector.execute(call)

    assert response.status == CallStatus.SUCCEEDED
    assert str(call.request_id) in captured["body"]
    assert call.incident_id in captured["body"]
