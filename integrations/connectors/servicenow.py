"""
ServiceNow connector — real Table API integration
(https://{instance}.service-now.com/api/now/table/{table}), not a
simulation. Falls back to a clear "not configured" failure rather than
pretending to succeed when SERVICENOW_INSTANCE_URL/credentials aren't set
— there is no sandbox instance available for this pass (see
integrations/README.md), so this is genuinely untested against a live
ServiceNow instance. It is tested against a mocked transport
(tests/test_connectors.py) to verify the request shape is right.

Capability -> table mapping is an MVP simplification: ServiceNow doesn't
have one universal "maintenance" table, so ScheduleMaintenance is modeled
as a change_request, same as CreateChangeRequest. A real deployment would
likely use a dedicated Maintenance/Work Order table depending on the
customer's ServiceNow app scope.
"""

import base64
import os
from typing import Optional

import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse

from .base import Connector

_CAPABILITY_TABLE = {
    Capability.CREATE_INCIDENT: "incident",
    Capability.CREATE_CHANGE_REQUEST: "change_request",
    Capability.SCHEDULE_MAINTENANCE: "change_request",
}


class ServiceNowConnector(Connector):
    name = "servicenow"
    capabilities = set(_CAPABILITY_TABLE.keys())

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        """`transport` is injectable so tests can use httpx.MockTransport
        instead of hitting a real (nonexistent, for this pass) instance."""
        self._transport = transport

    def _configured(self) -> tuple[Optional[str], Optional[str], Optional[str]]:
        return (
            os.environ.get("SERVICENOW_INSTANCE_URL"),
            os.environ.get("SERVICENOW_USERNAME"),
            os.environ.get("SERVICENOW_PASSWORD"),
        )

    def is_configured(self) -> bool:
        return all(self._configured())

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        instance_url, username, password = self._configured()
        if not instance_url or not username or not password:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="ServiceNow not configured: set SERVICENOW_INSTANCE_URL, "
                "SERVICENOW_USERNAME, SERVICENOW_PASSWORD (see .env.example)",
            )

        table = _CAPABILITY_TABLE[call.capability]
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

        async with httpx.AsyncClient(transport=self._transport, base_url=instance_url) as client:
            try:
                response = await client.post(
                    f"/api/now/table/{table}",
                    json=call.input,
                    headers={
                        "Authorization": f"Basic {credentials}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as e:
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error=f"ServiceNow request failed: {e}",
                )

        if response.status_code >= 400:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"ServiceNow returned {response.status_code}: {response.text[:500]}",
            )

        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output=response.json().get("result", {}),
        )
