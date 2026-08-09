"""
Smart Factory Connector — real & simulated REST integration against smart-factory-node
API Gateway (http://localhost:8000/api/v1/factory), fulfilling REROUTE_STATION,
EVALUATE_GNN_RISK, READ_RUL_TELEMETRY, SORT_WORKPIECE, UPDATE_MES, and RESERVE_INVENTORY.
"""

import os
from typing import Dict, Any, Optional
import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse
from .base import Connector

SMART_FACTORY_CAPABILITIES = {
    Capability.REROUTE_STATION,
    Capability.EVALUATE_GNN_RISK,
    Capability.READ_RUL_TELEMETRY,
    Capability.SORT_WORKPIECE,
    Capability.UPDATE_MES,
    Capability.RESERVE_INVENTORY,
}

#: Capabilities that move something in the physical plant. For these, losing
#: contact AFTER the request went out is genuinely ambiguous — the gripper may
#: have moved. The read-only ones (risk scores, telemetry) carry no such doubt:
#: a lost response to a GET means we simply do not know the value, and asking
#: again is free.
_SIDE_EFFECTING = {
    Capability.REROUTE_STATION,
    Capability.SORT_WORKPIECE,
    Capability.UPDATE_MES,
    Capability.RESERVE_INVENTORY,
}

#: Failures where the request provably never reached the gateway. Nothing
#: happened, so these are plainly FAILED and a retry is safe.
#: httpx raises ConnectError/ConnectTimeout before a byte is written, and
#: PoolTimeout before a connection is even acquired.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class SmartFactoryConnector(Connector):
    name = "smart_factory"
    capabilities = SMART_FACTORY_CAPABILITIES

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    def _base_url(self) -> str:
        return os.environ.get("SMART_FACTORY_GATEWAY_URL", "http://localhost:8000")

    def is_configured(self) -> bool:
        return True

    def _respond(self, call: CapabilityCall, resp: httpx.Response) -> CapabilityResponse:
        """One place where an HTTP reply becomes a capability outcome.

        The HTTP status is checked. Every branch previously called resp.json()
        and returned SUCCEEDED unconditionally, so a 400 or a 500 from the
        factory gateway was recorded as a completed action — the gateway's own
        error body ended up filed as the result of a successful reroute.

        `output=`, not `result=`. CapabilityResponse has no `result` field, so
        the original `result=data` was silently dropped by pydantic and every
        smart-factory capability returned SUCCEEDED with an EMPTY payload. The
        telemetry, the risk score and the station acknowledgement never reached
        the caller, and nothing anywhere reported a problem.
        """
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text[:2000]}

        if not resp.is_success:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                output=data if isinstance(data, dict) else {"raw": data},
                error=f"smart factory gateway returned HTTP {resp.status_code}",
            )
        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output=data if isinstance(data, dict) else {"raw": data},
        )

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        base_url = self._base_url()
        capability = call.capability
        target = call.input.get("target") or call.input.get("target_name") or "default_target"

        async with httpx.AsyncClient(transport=self._transport, base_url=base_url, timeout=10.0) as client:
            try:
                if capability == Capability.EVALUATE_GNN_RISK:
                    resp = await client.get("/api/v1/factory/twin/gnn-risk")
                    return self._respond(call, resp)

                elif capability == Capability.READ_RUL_TELEMETRY:
                    resp = await client.get("/api/v1/factory/twin/rul")
                    return self._respond(call, resp)

                elif capability == Capability.REROUTE_STATION:
                    payload = {"action": "reroute", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/vgr/action", json=payload)
                    return self._respond(call, resp)

                elif capability == Capability.SORT_WORKPIECE:
                    payload = {"action": "sort", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/sm/action", json=payload)
                    return self._respond(call, resp)

                elif capability == Capability.UPDATE_MES:
                    payload = {"action": "update_mes", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/mm/action", json=payload)
                    return self._respond(call, resp)

                elif capability == Capability.RESERVE_INVENTORY:
                    payload = {"action": "reserve_inventory", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/hbw/action", json=payload)
                    return self._respond(call, resp)

                else:
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.FAILED,
                        connector=self.name,
                        error=f"Unsupported capability '{capability}' for SmartFactoryConnector",
                    )

            except _NEVER_SENT as ex:
                # The request provably never left. Nothing happened in the
                # plant, so this is an honest FAILED and a retry is safe.
                #
                # This handler previously returned SUCCEEDED with a "simulated"
                # payload for EVERY exception, which made an unplugged factory
                # and a completed reroute indistinguishable in the audit trail:
                # ADOS recorded the workpiece as re-dispatched because nothing
                # threw on our side. A simulation mode, if wanted for demos,
                # needs an explicit opt-in flag visible in the response — never
                # an except clause.
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error=f"smart factory gateway unreachable, request never sent: "
                          f"{type(ex).__name__}: {ex}",
                )

            except Exception as ex:
                # Contact was lost with the request already in flight. For a
                # side-effecting capability the plant MAY have acted, and both
                # binary answers are wrong: SUCCEEDED claims an effect nobody
                # observed, FAILED invites a retry that could re-dispatch a
                # workpiece a second time.
                #
                # UNKNOWN is the honest answer, and it is a debt — something has
                # to reconcile it against the plant's own state before this call
                # can be called done.
                if call.capability in _SIDE_EFFECTING:
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.UNKNOWN,
                        connector=self.name,
                        error=f"contact lost after the command was sent; the plant may or "
                              f"may not have executed it — verify before retrying "
                              f"({type(ex).__name__}: {ex})",
                    )
                # Read-only: a lost response means we don't have the value.
                # Nothing changed out there, so asking again is free.
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error=f"smart factory read failed: {type(ex).__name__}: {ex}",
                )
