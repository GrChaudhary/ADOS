"""
SAP connector — real OData integration against SAP S/4HANA Cloud APIs
(API_PURCHASEORDER_PROCESS_SRV for CreatePurchaseOrder,
API_MATERIAL_STOCK_SRV for ReserveInventory), following SAP's standard
CSRF-token-then-POST flow. Same honesty note as servicenow.py: no SAP
sandbox instance is available for this pass, so this is untested against
a live SAP system — tested against a mocked transport instead
(tests/test_connectors.py).
"""

import os
from typing import Optional

import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse

from .base import Connector

_CAPABILITY_SERVICE_PATH = {
    Capability.CREATE_PURCHASE_ORDER: "/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder",
    Capability.RESERVE_INVENTORY: "/API_MATERIAL_STOCK_SRV/A_MatlStkInAcctMod",
}


class SAPConnector(Connector):
    name = "sap"
    capabilities = set(_CAPABILITY_SERVICE_PATH.keys())

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    def _configured(self) -> tuple[Optional[str], Optional[str]]:
        return os.environ.get("SAP_BASE_URL"), os.environ.get("SAP_API_KEY")

    def is_configured(self) -> bool:
        return all(self._configured())

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        base_url, api_key = self._configured()
        if not base_url or not api_key:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="SAP not configured: set SAP_BASE_URL, SAP_API_KEY (see .env.example)",
            )

        service_path = _CAPABILITY_SERVICE_PATH[call.capability]

        async with httpx.AsyncClient(transport=self._transport, base_url=base_url) as client:
            try:
                # SAP OData requires a CSRF token fetched via GET before any
                # state-changing POST/PUT/DELETE.
                token_response = await client.get(
                    service_path.rsplit("/", 1)[0] + "/",
                    headers={"APIKey": api_key, "x-csrf-token": "fetch"},
                )
                csrf_token = token_response.headers.get("x-csrf-token", "")

                response = await client.post(
                    service_path,
                    json=call.input,
                    headers={
                        "APIKey": api_key,
                        "x-csrf-token": csrf_token,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as e:
                return CapabilityResponse(
                    request_id=call.request_id,
                    status=CallStatus.FAILED,
                    connector=self.name,
                    error=f"SAP request failed: {e}",
                )

        if response.status_code >= 400:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"SAP returned {response.status_code}: {response.text[:500]}",
            )

        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output=response.json().get("d", {}),
        )
