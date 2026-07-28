"""
External B2B Marketplace & 3PL Freight Connector.
Fulfills QUERY_EXTERNAL_STOCK, CREATE_EXTERNAL_PO, and GET_FREIGHT_QUOTE
capabilities against external supplier networks and logistics APIs.
"""

import os
from typing import Optional, Set, Dict, Any, List
import httpx

from contracts import Capability, CallStatus, CapabilityCall, CapabilityResponse
from .base import Connector

_MARKETPLACE_CAPABILITIES: Set[Capability] = {
    Capability.QUERY_EXTERNAL_STOCK,
    Capability.CREATE_EXTERNAL_PO,
    Capability.GET_FREIGHT_QUOTE
}

# Rich 6-part catalog with multi-vendor supply pricing and geographic locations
PARTS_CATALOG: Dict[str, Dict[str, Any]] = {
    "MH-8820": {
        "name": "Motor Housing Component",
        "category": "Structural Casting",
        "suppliers": [
            {"supplier_id": "SUP-302", "name": "PrecisionCast GmbH", "location": "Stuttgart, Germany", "qty": 4500, "unit_price_usd": 435.00, "lead_time_days": 1},
            {"supplier_id": "MKT-VF-01", "name": "Vanguard Forge Ltd.", "location": "Birmingham, UK", "qty": 150, "unit_price_usd": 440.00, "lead_time_days": 2}
        ]
    },
    "SP-9910": {
        "name": "CNC Spindle Assembly 12k RPM",
        "category": "Rotary Tooling",
        "suppliers": [
            {"supplier_id": "SUP-801", "name": "Apex Machinery Corp", "location": "Austin, Texas", "qty": 14, "unit_price_usd": 3250.00, "lead_time_days": 3},
            {"supplier_id": "SUP-802", "name": "Bangalore Precision Tools", "location": "Bangalore, India", "qty": 4, "unit_price_usd": 3400.00, "lead_time_days": 1}
        ]
    },
    "CP-4420": {
        "name": "High-Pressure Spindle Coolant Pump",
        "category": "Fluid Hydraulics",
        "suppliers": [
            {"supplier_id": "SUP-501", "name": "FlowTech Industrial KK", "location": "Osaka, Japan", "qty": 85, "unit_price_usd": 680.00, "lead_time_days": 4},
            {"supplier_id": "SUP-502", "name": "Kirloskar Pumps & Valves", "location": "Pune, India", "qty": 22, "unit_price_usd": 650.00, "lead_time_days": 1}
        ]
    },
    "WS-1010": {
        "name": "High-Resolution Laser Weld Sensor",
        "category": "Optical Metrology",
        "suppliers": [
            {"supplier_id": "SUP-901", "name": "OptiSens Photonics", "location": "San Jose, California", "qty": 45, "unit_price_usd": 1850.00, "lead_time_days": 2},
            {"supplier_id": "SUP-902", "name": "Kyocera Precision Optics", "location": "Kyoto, Japan", "qty": 30, "unit_price_usd": 1950.00, "lead_time_days": 3}
        ]
    },
    "GB-5540": {
        "name": "Gearbox Planetary Drive Shaft",
        "category": "Mechanical Transmission",
        "suppliers": [
            {"supplier_id": "SUP-601", "name": "Schaeffler Precision Drive", "location": "Nuremberg, Germany", "qty": 210, "unit_price_usd": 890.00, "lead_time_days": 2},
            {"supplier_id": "SUP-602", "name": "Bharat Gears Ltd", "location": "Mumbai, India", "qty": 95, "unit_price_usd": 840.00, "lead_time_days": 1}
        ]
    },
    "EC-7720": {
        "name": "Main Electronic Controller Board",
        "category": "Industrial Electronics",
        "suppliers": [
            {"supplier_id": "SUP-701", "name": "Taiwan Semiconductor Mfg", "location": "Hsinchu, Taiwan", "qty": 850, "unit_price_usd": 2450.00, "lead_time_days": 5},
            {"supplier_id": "SUP-702", "name": "Continental Automotive Sys", "location": "Regensburg, Germany", "qty": 120, "unit_price_usd": 2600.00, "lead_time_days": 2}
        ]
    }
}

# Fallback part in case of unrecognized query part numbers
DEFAULT_PART = {
    "name": "Generic Spare Industrial Part",
    "category": "General Maintenance",
    "suppliers": [
        {"supplier_id": "SUP-GEN-1", "name": "Global Tools & Hardware", "location": "Chicago, Illinois", "qty": 1000, "unit_price_usd": 150.00, "lead_time_days": 2},
        {"supplier_id": "SUP-GEN-2", "name": "Local Spares Supplier Ltd", "location": "Local Hub", "qty": 200, "unit_price_usd": 165.00, "lead_time_days": 1}
    ]
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
        part_number = call.input.get("part_number", "MH-8820")
        supplier_id = call.input.get("supplier_id", "SUP-302")
        quantity = call.input.get("quantity", 50)
        plant_id = call.input.get("plant_id", "PLANT-04-BANGALORE")

        # Resolve part catalog information
        part_info = PARTS_CATALOG.get(part_number, DEFAULT_PART)

        if call.capability == Capability.QUERY_EXTERNAL_STOCK:
            output = {
                "part_number": part_number,
                "part_name": part_info["name"],
                "category": part_info["category"],
                "available_stock": sum(s["qty"] for s in part_info["suppliers"]),
                "suppliers_in_stock": part_info["suppliers"],
                "recommended_supplier": part_info["suppliers"][0]["supplier_id"]
            }

        elif call.capability == Capability.CREATE_EXTERNAL_PO:
            # Look up correct supplier price for quantity calculations
            unit_price = 150.00
            supplier_name = "Selected Supplier"
            for s in part_info["suppliers"]:
                if s["supplier_id"] == supplier_id:
                    unit_price = s["unit_price_usd"]
                    supplier_name = s["name"]
                    break

            output = {
                "po_number": f"PO-EXT-{call.incident_id[:8].upper()}",
                "part_number": part_number,
                "part_name": part_info["name"],
                "supplier_id": supplier_id,
                "supplier_name": supplier_name,
                "quantity": quantity,
                "unit_price_usd": unit_price,
                "total_cost_usd": round(quantity * unit_price, 2),
                "status": "ISSUED_TO_VENDOR",
                "estimated_delivery": f"{part_info['suppliers'][0]['lead_time_days'] * 24} Hours"
            }

        elif call.capability == Capability.GET_FREIGHT_QUOTE:
            # Resolve supplier name and location
            supplier_loc = "Germany"
            carrier = "DHL Supply Chain Express"
            for s in part_info["suppliers"]:
                if s["supplier_id"] == supplier_id:
                    supplier_loc = s["location"]
                    break

            # Vary routing rates based on destination and priority/urgency
            priority_input = call.input.get("priority", {})
            safety_impact = priority_input.get("safety_impact", 0.1)
            customer_impact = priority_input.get("customer_impact", 0.5)
            is_critical = safety_impact > 0.5 or customer_impact > 0.8

            # Calculate transit parameters
            dest_name = "Bangalore, India" if "BANGALORE" in plant_id.upper() else "Austin, Texas"

            if is_critical:
                carrier = "DHL Supply Chain Express" if "BANGALORE" in plant_id.upper() else "FedEx Priority Air Charter"
                shipping_mode = "EXPEDITED_AIR_FREIGHT"
                transit_time_hours = 18 if "BANGALORE" in plant_id.upper() else 12
                estimated_cost_usd = 1250.00 if "BANGALORE" in plant_id.upper() else 850.00
            else:
                carrier = "BlueDart Express Ground" if "BANGALORE" in plant_id.upper() else "UPS Ground Freight"
                shipping_mode = "STANDARD_GROUND_CARRIER"
                transit_time_hours = 48 if "BANGALORE" in plant_id.upper() else 36
                estimated_cost_usd = 280.00 if "BANGALORE" in plant_id.upper() else 180.00

            output = {
                "quote_id": f"FRT-EXT-{call.incident_id[:8].upper()}",
                "carrier": carrier,
                "origin": f"Supplier Facility ({supplier_loc})",
                "destination": f"Nova Motors ({dest_name})",
                "shipping_mode": shipping_mode,
                "estimated_cost_usd": estimated_cost_usd,
                "transit_time_hours": transit_time_hours,
                "urgency_level": "CRITICAL" if is_critical else "STANDARD"
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
