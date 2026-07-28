"""
IBM watsonx Orchestrate ITSM Agent Connector.
Fulfills CREATE_INCIDENT, CREATE_CHANGE_REQUEST, SCHEDULE_MAINTENANCE, and NOTIFY_OPERATOR
capabilities by delegating to the tenant's real, live ServiceNow toolkit agents
registered in watsonx Orchestrate (confirmed via GET /v1/orchestrate/agents —
see test_connection()).
"""

import json
import os
import re
from typing import Optional, Dict, Any, Set
import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse, PolicyTier
from .base import Connector

_ITSM_CAPABILITIES: Set[Capability] = {
    Capability.CREATE_INCIDENT,
    Capability.CREATE_CHANGE_REQUEST,
    Capability.SCHEDULE_MAINTENANCE,
    Capability.NOTIFY_OPERATOR
}

# ados_itsm_agent — a small, dedicated agent (2 tools: create_incident,
# get_incident, both in orchestrate/servicenow_itsm_tools.py) against a
# ServiceNow PDI ADOS controls directly, replacing the earlier
# ados_executive_copilot reuse (a KPI-reporting agent hand-extended with 32
# ServiceNow tools whose connection had gone unconfigured). Live-verified:
# get_incident returned a real record (INC0000001) over the actual
# ServiceNow Table API. See orchestrate/ITSM_AGENT_SETUP.md for the setup
# SOP. All four ITSM capabilities route here — the agent only has a
# create/get incident tool, so CREATE_CHANGE_REQUEST/SCHEDULE_MAINTENANCE/
# NOTIFY_OPERATOR all land as a ServiceNow incident record too, same as
# they did against the old agent.
_INCIDENT_AGENT_ID = "88807f44-1398-4fac-9a31-de5237659622"

_AGENT_ID_BY_CAPABILITY: Dict[Capability, str] = {
    Capability.CREATE_INCIDENT: _INCIDENT_AGENT_ID,
    Capability.CREATE_CHANGE_REQUEST: _INCIDENT_AGENT_ID,
    Capability.SCHEDULE_MAINTENANCE: _INCIDENT_AGENT_ID,
    Capability.NOTIFY_OPERATOR: _INCIDENT_AGENT_ID,
}

# ADOS has no native impact/urgency taxonomy; ServiceNow's is derived from
# the governance tier already attached to every CapabilityCall.
_POLICY_TIER_TO_IMPACT_URGENCY: Dict[PolicyTier, str] = {
    PolicyTier.EXECUTIVE_APPROVAL: "1 - High",
    PolicyTier.APPROVAL_REQUIRED: "2 - Medium",
    PolicyTier.AUTONOMOUS: "3 - Low",
}


def _derive_itsm_fields(call: CapabilityCall) -> Dict[str, Any]:
    """Builds ServiceNow-shaped fields from the generic input the
    orchestrator actually sends (execution_steps/target_line_id — see
    agents/rerouting_agent.py) plus governance context already present on
    every call. Self-contained here, no orchestrator changes, matching
    marketplace.py's existing call.input.get(key, default) pattern."""
    execution_steps = call.input.get("execution_steps") or []

    short_description = call.input.get("short_description")
    if not short_description and execution_steps:
        first_step = re.sub(r"^\d+\.\s*", "", str(execution_steps[0])).strip()
        short_description = f"[ADOS {call.capability.value}] {first_step}"[:160]
    if not short_description:
        target_line = call.input.get("target_line_id", "unknown line")
        short_description = f"ADOS {call.capability.value} for incident {call.incident_id} on {target_line}"

    description = call.input.get("description")
    if not description and execution_steps:
        description = "\n".join(str(step) for step in execution_steps)

    default_impact_urgency = _POLICY_TIER_TO_IMPACT_URGENCY.get(call.governance.policy_tier, "3 - Low")

    fields: Dict[str, Any] = {
        "short_description": short_description,
        "impact": call.input.get("impact") or default_impact_urgency,
        "urgency": call.input.get("urgency") or default_impact_urgency,
    }
    if description:
        fields["description"] = description
    for optional_key in ("assignment_group", "caller_username", "incident_category"):
        if call.input.get(optional_key):
            fields[optional_key] = call.input[optional_key]
    return fields


def _build_prompt(call: CapabilityCall, fields: Dict[str, Any]) -> str:
    lines = [
        f"Create a ServiceNow record for this {call.capability.value} request now, using the "
        "details below. Do not ask clarifying questions — use the values given and reasonable "
        "defaults for anything not specified. After taking the action, end your reply with "
        "exactly one line in this exact format (no other text on that line): "
        'RESULT: {"status": "created", "ticket_id": "<id>", "reason": null} on success, or '
        'RESULT: {"status": "failed", "ticket_id": null, "reason": "<short reason>"} on failure.',
        "",
        f"short_description: {fields['short_description']}",
        f"impact: {fields['impact']}",
        f"urgency: {fields['urgency']}",
    ]
    for key in ("description", "assignment_group", "caller_username", "incident_category"):
        if key in fields:
            lines.append(f"{key}: {fields[key]}")
    return "\n".join(lines)


def _extract_reply_content(response_text: str) -> Optional[str]:
    """The chat/completions endpoint sometimes returns a single JSON
    object and sometimes a `text/event-stream` body (a sequence of
    `data: {...}` lines) even without `stream: true` in the request —
    observed switching between the two for the same agent/endpoint
    across calls. For the streamed shape, intermediate lines carry only
    partial `choices[0].delta.content` chunks; the final line (typically
    `object == "thread.message.completed"`) carries the full text in
    `choices[0].message.content`, same field name as the non-streamed
    shape. Scans from the end so it finds that full-content line without
    having to special-case the "completed" marker itself."""
    text = response_text.strip()
    if not text:
        return None

    if not text.startswith("data:"):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            data = json.loads(line[len("data:"):].strip())
        except ValueError:
            continue
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            continue
        message = choices[0].get("message")
        if isinstance(message, dict) and message.get("content"):
            return message["content"]
    return None


def _parse_result_trailer(reply_text: str) -> Optional[Dict[str, Any]]:
    """Finds the last `RESULT: {...}` line in the agent's free-text reply
    and parses it. Returns None if missing/unparseable — e.g. the agent
    asked a clarifying question instead of completing the action."""
    if not reply_text:
        return None
    idx = reply_text.rfind("RESULT:")
    if idx == -1:
        return None
    try:
        parsed = json.loads(reply_text[idx + len("RESULT:"):].strip())
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


class WatsonxITSMConnector(Connector):
    """
    Connector adapter for IBM watsonx Orchestrate's real ServiceNow toolkit
    agents. Translates ADOS capability calls into a natural-language
    request to a specific, real agent (confirmed live and write-capable —
    see test_connection() and _INCIDENT_AGENT_ID above), and parses a
    structured result trailer out of its free-text reply.
    """
    name = "watsonx_itsm"
    capabilities = _ITSM_CAPABILITIES

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    def _configured(self) -> tuple[Optional[str], Optional[str]]:
        return (
            os.environ.get("WO_INSTANCE"),
            os.environ.get("WO_API_KEY")
        )

    def is_configured(self) -> bool:
        # Deliberately requires a second, explicit opt-in beyond WO_INSTANCE/
        # WO_API_KEY: those two are set to activate the watsonx Orchestrate
        # ADK CLI (orchestrate env activate), a separate concern from
        # authorizing this connector to be selected at all. See
        # execute()'s WO_ITSM_LIVE_WRITES_ENABLED check for the further,
        # independent gate on actually writing a real ServiceNow record.
        instance_url, api_key = self._configured()
        return bool(instance_url and api_key and os.environ.get("WO_ITSM_INTEGRATION_ENABLED") == "true")

    async def _get_iam_token(self, api_key: str, client: httpx.AsyncClient) -> Optional[str]:
        """Exchanges IBM Cloud API key for an IAM Bearer access token."""
        try:
            resp = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            if resp.status_code == 200:
                return resp.json().get("access_token")
        except Exception:
            pass
        return None

    async def test_connection(self) -> Dict[str, Any]:
        """Read-only reachability check: IAM token exchange + GET
        /v1/orchestrate/agents against WO_INSTANCE. Makes no state-changing
        calls, so it's safe to run regardless of WO_ITSM_INTEGRATION_ENABLED
        or WO_ITSM_LIVE_WRITES_ENABLED — both only gate execute()."""
        instance_url, api_key = self._configured()
        if not instance_url or not api_key:
            return {"connected": False, "error": "WO_INSTANCE / WO_API_KEY not set"}

        async with httpx.AsyncClient(transport=self._transport) as client:
            token = await self._get_iam_token(api_key, client)
            if not token:
                return {"connected": False, "error": "IAM token exchange failed"}

            try:
                response = await client.get(
                    f"{instance_url.rstrip('/')}/v1/orchestrate/agents",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=10.0,
                )
            except httpx.HTTPError as e:
                return {"connected": False, "error": f"request failed: {e}"}

        if response.status_code != 200:
            return {"connected": False, "error": f"{response.status_code}: {response.text[:300]}"}

        agents = response.json()
        return {
            "connected": True,
            "agent_count": len(agents),
            "agents": [a.get("name") for a in agents if isinstance(a, dict) and a.get("name")],
        }

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        # Independent of is_configured(): that gate controls whether this
        # connector is even SELECTED by the policy engine (so request-
        # shaping/selection logic stays fully testable); this gate is the
        # last line of defense against ever making a real ServiceNow
        # write, checked before any network call at all. CREATE_INCIDENT
        # is governance-classified "low" risk (orchestrate/governance.py)
        # and can therefore fire autonomously with no human approval —
        # without this second flag, enabling the integration would let
        # every qualifying incident silently create a real ticket.
        if os.environ.get("WO_ITSM_LIVE_WRITES_ENABLED") != "true":
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="watsonx Orchestrate ITSM live writes are disabled "
                      "(set WO_ITSM_LIVE_WRITES_ENABLED=true to allow this connector "
                      "to create/modify real ServiceNow records)",
            )

        instance_url, api_key = self._configured()
        if not instance_url or not api_key:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="watsonx Orchestrate ITSM not configured: set WO_INSTANCE and WO_API_KEY in .env"
            )

        agent_id = os.environ.get("WO_ITSM_AGENT_ID") or _AGENT_ID_BY_CAPABILITY.get(call.capability)
        if not agent_id:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"watsonx Orchestrate ITSM: no agent mapped for capability {call.capability.value}",
            )

        fields = _derive_itsm_fields(call)
        prompt = _build_prompt(call, fields)

        async with httpx.AsyncClient(transport=self._transport) as client:
            token = await self._get_iam_token(api_key, client)
            if not token:
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error="watsonx Orchestrate ITSM: IAM token exchange failed",
                )

            try:
                response = await client.post(
                    f"{instance_url.rstrip('/')}/v1/orchestrate/{agent_id}/chat/completions",
                    json={"messages": [{"role": "user", "content": prompt}]},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )
            except httpx.HTTPError as e:
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error=f"watsonx Orchestrate ITSM request failed: {e}",
                )

        if response.status_code != 200:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"watsonx Orchestrate ITSM returned {response.status_code}: {response.text[:500]}",
            )

        reply_text = _extract_reply_content(response.text)
        if reply_text is None:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"watsonx Orchestrate ITSM: unexpected response shape: {response.text[:500]}",
            )

        result = _parse_result_trailer(reply_text)
        if not result:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="watsonx ITSM agent did not return a structured result (it may have asked "
                      f"a clarifying question instead of acting): {reply_text[:300]}",
            )

        if result.get("status") != "created" or not result.get("ticket_id"):
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"watsonx ITSM agent reported failure: {result.get('reason') or 'no reason given'}",
            )

        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output={"ticket_id": result["ticket_id"], "raw_reply": reply_text[:500]},
        )
