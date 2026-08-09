"""
Manufacturing & Supply Chain domain pod action registry for the Main Orchestrating Agent (MOA).

Exposes Manufacturing-specific capability tools, risk classifications, and action specifications.
Integrates with L5 Governance (orchestrate/governance.py) and IntegrationHub (integrations/hub.py).
"""

from dataclasses import dataclass
from typing import Dict, Any

from contracts import Capability


@dataclass(frozen=True)
class ManufacturingAction:
    key: str
    description: str
    capability: Capability
    estimated_cost_usd: float


MANUFACTURING_ACTIONS: Dict[str, ManufacturingAction] = {
    "query_external_stock": ManufacturingAction(
        key="query_external_stock",
        description="Query supplier inventory and external stock levels",
        capability=Capability.QUERY_EXTERNAL_STOCK,
        estimated_cost_usd=0.0,
    ),
    "reserve_inventory": ManufacturingAction(
        key="reserve_inventory",
        description="Reserve plant inventory stock in High-Bay Warehouse (HBW) for production line run",
        capability=Capability.RESERVE_INVENTORY,
        estimated_cost_usd=5000.0,
    ),
    "update_mes": ManufacturingAction(
        key="update_mes",
        description="Update Manufacturing Execution System line parameters and recipe configuration",
        capability=Capability.UPDATE_MES,
        estimated_cost_usd=40000.0,
    ),
    "schedule_maintenance": ManufacturingAction(
        key="schedule_maintenance",
        description="Schedule equipment preventive maintenance window on production line",
        capability=Capability.SCHEDULE_MAINTENANCE,
        estimated_cost_usd=40000.0,
    ),
    "create_purchase_order": ManufacturingAction(
        key="create_purchase_order",
        description="Create capital equipment purchase order for replacement components",
        capability=Capability.CREATE_PURCHASE_ORDER,
        estimated_cost_usd=250000.0,
    ),
    "reroute_station": ManufacturingAction(
        key="reroute_station",
        description="Re-dispatch workpiece via Vacuum Gripper Robot (VGR) to alternative production line",
        capability=Capability.REROUTE_STATION,
        estimated_cost_usd=2000.0,
    ),
    "evaluate_gnn_risk": ManufacturingAction(
        key="evaluate_gnn_risk",
        description="Query Graph Neural Network (GNN) model for plant-wide cascading risk scores",
        capability=Capability.EVALUATE_GNN_RISK,
        estimated_cost_usd=0.0,
    ),
    "read_rul_telemetry": ManufacturingAction(
        key="read_rul_telemetry",
        description="Ingest Remaining Useful Life (RUL) and machine wear telemetry from Digital Twin",
        capability=Capability.READ_RUL_TELEMETRY,
        estimated_cost_usd=0.0,
    ),
    "sort_workpiece": ManufacturingAction(
        key="sort_workpiece",
        description="Trigger Sorting Machine (SM) pneumatic ejectors based on optical/thermal vision",
        capability=Capability.SORT_WORKPIECE,
        estimated_cost_usd=500.0,
    ),
}


def execute_manufacturing_action(action_key: str, target_name: str) -> Dict[str, Any]:
    """Execution helper for Manufacturing domain capabilities."""
    action = MANUFACTURING_ACTIONS.get(action_key)
    if not action:
        return {"status": "error", "error": f"Unknown Manufacturing action: {action_key}"}

    return {
        "status": "success",
        "action": action_key,
        "capability": action.capability.value,
        "message": f"Manufacturing action '{action_key}' executed for {target_name}.",
    }
