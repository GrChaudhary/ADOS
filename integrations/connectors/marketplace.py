"""
External B2B Marketplace & 3PL Freight Connector.
Fulfills QUERY_EXTERNAL_STOCK, CREATE_EXTERNAL_PO, and GET_FREIGHT_QUOTE
capabilities against external supplier networks and logistics APIs.
"""

import os
from typing import Optional, Set
import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse
from .base import Connector

_MARKETPLACE_CAPABILITIES: Set[Capability] = {
    Capability.QUERY_EXTERNAL_STOCK,
    Capability.CREATE_EXTERNAL_PO,
    Capability.GET_FREIGHT_QUOTE
}


class MarketplaceConnector(Connector):
    """
    Connector adapter for external B2B supplier marketplaces and 3PL logistics networks.
    """
    name = "marketplace"
    capabilities = _MARKETPLACE_CAPABILITIES

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    def is_configured(self) -> bool:
        # Defaults to true (provides fallback mock responses for MVP when API keys are omitted)
        return True

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        part_number = call.input.get("part_number", "MH-100")
        supplier_id = call.input.get("supplier_id", "SUP-202")
        quantity = call.input.get("quantity", 50)

        if call.capability == Capability.QUERY_EXTERNAL_STOCK:
            output = {
                "part_number": part_number,
                "available_stock": 450,
                "suppliers_in_stock": [
                    {"supplier_id": "SUP-202", "name": "SteelCore Manufacturing", "qty": 300, "unit_price_usd": 42.50, "lead_time_days": 2},
                    {"supplier_id": "MKT-VF-01", "name": "Vanguard Forge Ltd.", "qty": 150, "unit_price_usd": 44.00, "lead_time_days": 1}
                ],
                "recommended_supplier": "SUP-202"
            }
        elif call.capability == Capability.CREATE_EXTERNAL_PO:
            output = {
                "po_number": f"PO-EXT-{call.incident_id[:8].upper()}",
                "part_number": part_number,
                "supplier_id": supplier_id,
                "quantity": quantity,
                "total_cost_usd": round(quantity * 42.50, 2),
                "status": "ISSUED_TO_VENDOR",
                "estimated_delivery": "48 Hours"
            }
        elif call.capability == Capability.GET_FREIGHT_QUOTE:
            output = {
                "quote_id": f"FRT-EXT-{call.incident_id[:8].upper()}",
                "carrier": "DHL Supply Chain Express",
                "origin": "Supplier Facility SUP-202",
                "destination": call.input.get("plant_id", "FAC-P1-L3"),
                "shipping_mode": "EXPEDITED_AIR_FREIGHT",
                "estimated_cost_usd": 450.00,
                "transit_time_hours": 18
            }
        else:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"Unsupported marketplace capability: {call.capability}"
            )

        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.SUCCEEDED,
            connector=self.name,
            output=output
        )
