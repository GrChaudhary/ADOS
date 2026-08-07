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

To verify against a real instance (a free Personal Developer Instance is
enough), see docs/SERVICENOW_PILOT.md and run:

    ./.venv/bin/python scripts/servicenow_smoke.py

That script creates a real ticket, reads it back, and prints its URL. It is
the difference between "the request shape looks right against a mock" and
"a ticket exists" — until someone runs it, this connector is unverified.
"""

import base64
import os
from typing import Optional

import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse

from .base import Connector
from .servicenow_fields import build_record

_CAPABILITY_TABLE = {
    Capability.CREATE_INCIDENT: "incident",
    Capability.CREATE_CHANGE_REQUEST: "change_request",
    Capability.SCHEDULE_MAINTENANCE: "change_request",
    # HR offboarding (orchestrate/moa/hr_domain.py). change_request is the
    # right stock-instance home for these: each one is a deliberate,
    # approved change to a system of record, which is exactly what the
    # change_request table is for, and it exists on a bare Personal
    # Developer Instance with zero configuration. A production deployment
    # with a configured Service Catalog would more likely route these to
    # sc_req_item/sc_task off an "Employee Offboarding" catalog item --
    # same simplification, and for the same reason, as SCHEDULE_MAINTENANCE
    # above.
    #
    # NOTIFY_MANAGER is deliberately NOT here. It is a notification, not a
    # ticket, and there is no mail connector wired up -- routing it to
    # ServiceNow just to have it "hit something real" would be dressing up
    # a gap. It stays on ConsoleConnector, honestly simulated.
    Capability.REVOKE_BUILDING_ACCESS: "change_request",
    Capability.DISABLE_IT_ACCESS: "change_request",
    Capability.STOP_PAYROLL: "change_request",
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
        # Never post call.input raw — ServiceNow silently ignores unknown
        # fields and still returns 201, so an unmapped payload creates a
        # blank ticket and reports success. See servicenow_fields.py.
        record = build_record(call.capability, call.input)
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()

        async with httpx.AsyncClient(transport=self._transport, base_url=instance_url) as client:
            try:
                response = await client.post(
                    f"/api/now/table/{table}",
                    json=record,
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
