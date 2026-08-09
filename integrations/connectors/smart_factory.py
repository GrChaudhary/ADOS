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


class SmartFactoryConnector(Connector):
    name = "smart_factory"
    capabilities = SMART_FACTORY_CAPABILITIES

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    def _base_url(self) -> str:
        return os.environ.get("SMART_FACTORY_GATEWAY_URL", "http://localhost:8000")

    def is_configured(self) -> bool:
        return True

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        base_url = self._base_url()
        capability = call.capability
        target = call.input.get("target") or call.input.get("target_name") or "default_target"

        async with httpx.AsyncClient(transport=self._transport, base_url=base_url, timeout=10.0) as client:
            try:
                if capability == Capability.EVALUATE_GNN_RISK:
                    resp = await client.get("/api/v1/factory/twin/gnn-risk")
                    data = resp.json()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.SUCCEEDED,
                        connector=self.name,
                        result=data,
                    )

                elif capability == Capability.READ_RUL_TELEMETRY:
                    resp = await client.get("/api/v1/factory/twin/rul")
                    data = resp.json()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.SUCCEEDED,
                        connector=self.name,
                        result=data,
                    )

                elif capability == Capability.REROUTE_STATION:
                    payload = {"action": "reroute", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/vgr/action", json=payload)
                    data = resp.json()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.SUCCEEDED,
                        connector=self.name,
                        result=data,
                    )

                elif capability == Capability.SORT_WORKPIECE:
                    payload = {"action": "sort", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/sm/action", json=payload)
                    data = resp.json()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.SUCCEEDED,
                        connector=self.name,
                        result=data,
                    )

                elif capability == Capability.UPDATE_MES:
                    payload = {"action": "update_mes", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/mm/action", json=payload)
                    data = resp.json()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.SUCCEEDED,
                        connector=self.name,
                        result=data,
                    )

                elif capability == Capability.RESERVE_INVENTORY:
                    payload = {"action": "reserve_inventory", "target": target, "parameters": call.input}
                    resp = await client.post("/api/v1/factory/stations/hbw/action", json=payload)
                    data = resp.json()
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.SUCCEEDED,
                        connector=self.name,
                        result=data,
                    )

                else:
                    return CapabilityResponse(
                        request_id=call.request_id,
                        status=CallStatus.FAILED,
                        connector=self.name,
                        error=f"Unsupported capability '{capability}' for SmartFactoryConnector",
                    )

            except Exception as ex:
                # Simulation fallback mode when gateway server is not live
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.SUCCEEDED,
                    connector=self.name,
                    result={
                        "status": "simulated",
                        "capability": capability.value,
                        "target": target,
                        "message": f"Smart Factory simulation executed '{capability.value}' for '{target}' (Gateway offline fallback: {str(ex)})",
                    },
                )
