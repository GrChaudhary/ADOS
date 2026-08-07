"""
Translates an ADOS CapabilityCall.input into a real ServiceNow record.

Why this exists — a real defect, not a refactor. `ServiceNowConnector` used
to POST `call.input` straight to the Table API. That works only if the
caller already happens to speak ServiceNow's field vocabulary, which is true
of exactly one caller: `orchestrate/langgraph_agents/itsm_agent.py` sends
`{"short_description": ..., "description": ...}`.

The MOA does not. `orchestrate/moa/graph.py:_action_input()` builds
`{"employee_name": "Jane Doe", "action": "stop_payroll"}` — none of which are
ServiceNow columns. ServiceNow's Table API silently ignores unknown fields
and returns 201, so an offboarding would have reported SUCCEEDED while
creating an essentially blank record with no description, no assignment, and
nothing tying it back to the task that asked for it. Worse than failing,
because the audit trail would record a success.

So the translation is explicit and per-capability here, and the connector
never posts raw input again.
"""

from typing import Any, Dict

from contracts import Capability

# ADOS bookkeeping that must never be posted as a ServiceNow field. These
# carry real meaning, so they are folded into the description below rather
# than dropped silently.
_ADOS_INTERNAL_KEYS = {"action", "capability_id", "employee_name"}

# ServiceNow urgency/impact are 1(high)/2(medium)/3(low) on a stock instance.
_HIGH, _MEDIUM = "2", "3"

_HR_OFFBOARDING_SUMMARY = {
    Capability.REVOKE_BUILDING_ACCESS: (
        "Revoke building access for {employee}",
        "Offboarding: disable all badge and physical site access for {employee}. "
        "Raised automatically by ADOS and approved through its governance layer.",
        _MEDIUM,
    ),
    Capability.DISABLE_IT_ACCESS: (
        "Disable IT access for {employee}",
        "Offboarding: disable directory, email, VPN, and SSO access for {employee}. "
        "Raised automatically by ADOS and approved through its governance layer.",
        _HIGH,
    ),
    Capability.STOP_PAYROLL: (
        "Stop payroll for {employee}",
        "Offboarding: halt further payroll disbursement for {employee}. "
        "Raised automatically by ADOS and approved through its governance layer.",
        _HIGH,
    ),
}


def _passthrough(record: Dict[str, Any]) -> Dict[str, Any]:
    """Caller already speaks ServiceNow. Strip ADOS-internal keys and post
    the rest as-is — this is the itsm_agent.py path, which has always sent
    real field names and must keep working unchanged."""
    return {k: v for k, v in record.items() if k not in _ADOS_INTERNAL_KEYS}


def build_record(capability: Capability, call_input: Dict[str, Any]) -> Dict[str, Any]:
    """Returns the dict to POST to ServiceNow's Table API.

    Two shapes are accepted, distinguished by whether the caller supplied
    `short_description` — ServiceNow's one effectively-required field on both
    the incident and change_request tables:

    1. Already ServiceNow-shaped (itsm_agent.py): passed through untouched
       apart from stripping ADOS-internal keys.
    2. An ADOS domain action (MOA): translated into a real record here.

    Deliberately not a generic key-renaming table. Each capability gets a
    written summary and description because a ticket a human has to act on
    needs prose, not a serialized dict.
    """
    if call_input.get("short_description"):
        return _passthrough(call_input)

    employee = call_input.get("employee_name") or "an unnamed employee"

    summary = _HR_OFFBOARDING_SUMMARY.get(capability)
    if summary is not None:
        short_description, description, urgency = summary
        return {
            "short_description": short_description.format(employee=employee),
            "description": description.format(employee=employee),
            "urgency": urgency,
            "category": "Inquiry / Help",
        }

    # Any other capability reaching ServiceNow without a short_description.
    # Fail loudly in prose rather than posting a blank ticket: an operator
    # reading this in ServiceNow can see exactly what asked for it.
    action = call_input.get("action") or capability.value
    return {
        "short_description": f"{capability.value} requested by ADOS ({action})",
        "description": (
            f"ADOS requested capability {capability.value} (action '{action}') "
            f"for {employee}. No ServiceNow field mapping is defined for this "
            f"capability yet — see integrations/connectors/servicenow_fields.py. "
            f"Raw request: {call_input!r}"
        ),
        "urgency": _MEDIUM,
    }
