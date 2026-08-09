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
    # NotifyITHelpdesk -> a real incident record. Until now this capability had
    # no real connector and fell through to ConsoleConnector, which returned
    # "[console] simulated NotifyITHelpdesk" — the acceptance run's one
    # remaining simulated step. An IT helpdesk notification IS an incident on a
    # stock instance, so this needs no new table and no new client.
    #
    # Note the contrast with NOTIFY_MANAGER below, which stays on Console: that
    # one is a person-to-person notification with no ticket semantics, and
    # routing it here just to make it "hit something real" would be dressing up
    # a gap. This one genuinely is a ticket.
    Capability.NOTIFY_IT_HELPDESK: "incident",
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

    @staticmethod
    def _auth_header(username: str, password: str) -> str:
        return base64.b64encode(f"{username}:{password}".encode()).decode()

    async def resolve_record(
        self,
        table: str,
        sys_id: str,
        *,
        close_notes: str,
        state: str = "7",
        close_code: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Close a record this connector created. Returns (ok, detail).

        Exists for the explicit external-side-effect test, which must not leave
        a growing pile of open tickets in a real instance. Deliberately
        RESOLVE/CLOSE rather than DELETE: closing is the normal ServiceNow
        lifecycle and leaves the audit trail intact, whereas deleting would
        destroy the very evidence the test was created to produce.

        state 7 = Closed on a stock incident table (6 = Resolved).

        `close_code` is VERSION-DEPENDENT and its values are a per-instance
        choice list, so it is configurable rather than hardcoded. This was found
        the hard way: closing with "Closed/Resolved by Caller" — correct on
        older instances — returned

            403 Data Policy Exception: The following fields are mandatory:
                Resolution code

        because the instance rejects an unknown choice and then reports the
        field as unset. The failure is indistinguishable from omitting it.
        Override with SERVICENOW_CLOSE_CODE; check a target instance with

            GET /api/now/table/sys_choice?sysparm_query=name=incident^element=close_code

        Reuses this connector's own credentials and base URL rather than
        standing up a second client — the request is a PATCH to the same Table
        API this class already speaks.
        """
        instance_url, username, password = self._configured()
        if not instance_url or not username or not password:
            return False, "ServiceNow not configured"

        async with httpx.AsyncClient(transport=self._transport, base_url=instance_url) as client:
            try:
                response = await client.patch(
                    f"/api/now/table/{table}/{sys_id}",
                    json={
                        "state": state,
                        "close_code": close_code
                        or os.environ.get("SERVICENOW_CLOSE_CODE", "Resolved by caller"),
                        "close_notes": close_notes,
                    },
                    headers={
                        "Authorization": f"Basic {self._auth_header(username, password)}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as e:
                return False, f"ServiceNow PATCH failed: {e}"

        if response.status_code >= 400:
            return False, f"ServiceNow returned {response.status_code}: {response.text[:300]}"
        return True, str(response.json().get("result", {}).get("state", ""))

    async def fetch_record(self, table: str, sys_id: str) -> tuple[bool, dict]:
        """Read a record back. Independent verification for the explicit test:
        a 201 from the POST says ADOS sent something, not that a ticket exists.
        """
        instance_url, username, password = self._configured()
        if not instance_url or not username or not password:
            return False, {"error": "ServiceNow not configured"}

        async with httpx.AsyncClient(transport=self._transport, base_url=instance_url) as client:
            try:
                response = await client.get(
                    f"/api/now/table/{table}/{sys_id}",
                    headers={
                        "Authorization": f"Basic {self._auth_header(username, password)}",
                        "Accept": "application/json",
                    },
                )
            except httpx.HTTPError as e:
                return False, {"error": str(e)}

        if response.status_code >= 400:
            return False, {"error": f"HTTP {response.status_code}", "body": response.text[:300]}
        return True, response.json().get("result", {})

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
        record = build_record(
            call.capability,
            call.input,
            # The gateway sets incident_id to the mission id and requested_by to
            # the originating runtime, so provenance lands in the ticket rather
            # than only in ADOS's database.
            {
                "mission_id": call.incident_id,
                "request_id": call.request_id,
                "requested_by": call.requested_by,
            },
        )
        credentials = self._auth_header(username, password)

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
