"""
IBM watsonx Orchestrate ITSM Agent Connector.
Fulfills CREATE_INCIDENT, CREATE_CHANGE_REQUEST, SCHEDULE_MAINTENANCE, and NOTIFY_OPERATOR
capabilities by delegating to the IBM watsonx Orchestrate ITSM Agent & toolkits.
"""

import os
from typing import Optional, Dict, Any, Set
import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse
from .base import Connector

_ITSM_CAPABILITIES: Set[Capability] = {
    Capability.CREATE_INCIDENT,
    Capability.CREATE_CHANGE_REQUEST,
    Capability.SCHEDULE_MAINTENANCE,
    Capability.NOTIFY_OPERATOR
}


class WatsonxITSMConnector(Connector):
    """
    Connector adapter for IBM watsonx Orchestrate ITSM Agent / ServiceNow Toolkit.
    Translates ADOS capability calls into Watsonx Orchestrate ITSM execution payloads.
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
        # authorizing this hand-rolled REST integration against an endpoint
        # (/v1/agents/itsm/run) that hasn't been verified to exist. Without
        # this, every backend process and every test run would silently
        # start making live IAM token-exchange calls the moment the ADK key
        # is present — which is exactly what happened before this fix (a
        # unit test making a real network call, taking 12s, with no test
        # asserting on it).
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

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        instance_url, api_key = self._configured()
        if not instance_url or not api_key:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="watsonx Orchestrate ITSM not configured: set WO_INSTANCE and WO_API_KEY in .env"
            )

        async with httpx.AsyncClient(transport=self._transport) as client:
            token = await self._get_iam_token(api_key, client)
            if not token:
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error="watsonx Orchestrate ITSM: IAM token exchange failed",
                )

            # Invoke Orchestrate Agent REST API endpoint
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }

            itsm_payload = {
                "capability": call.capability.value,
                "incidentId": call.incident_id,
                "requestedBy": call.requested_by,
                "input": call.input,
                "governance": call.governance.model_dump(by_alias=True)
            }

            # NOTE: /v1/agents/itsm/run is not a documented/verified watsonx
            # Orchestrate REST endpoint — it hasn't been confirmed against a
            # live instance. This connector reports FAILED rather than
            # fabricating a ticket ID when the call doesn't succeed, so a
            # wrong or not-yet-real endpoint shows up as a real failure in
            # the audit trail instead of silently polluting it with fake
            # "SUCCEEDED" records (docs/007-governance.md's audit trail is
            # meant to be trustworthy, not optimistic).
            try:
                response = await client.post(
                    f"{instance_url.rstrip('/')}/v1/agents/itsm/run",
                    json=itsm_payload,
                    headers=headers,
                    timeout=10.0
                )
            except httpx.HTTPError as e:
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error=f"watsonx Orchestrate ITSM request failed: {e}",
                )

            if response.status_code not in (200, 201):
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error=f"watsonx Orchestrate ITSM returned {response.status_code}: {response.text[:500]}",
                )

            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.SUCCEEDED,
                connector=self.name,
                output=response.json().get("result", {}),
            )
