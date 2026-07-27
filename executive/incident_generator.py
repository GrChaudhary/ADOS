"""
Deterministic generator for Nova Motors historical incident fixtures.

Produces a reproducible (seeded) batch of IncidentRecord entries spanning all
8 categories from Blueprints/ADOS_Demo_Product_Experience_Blueprint.md's
"Demo Dataset" section, so Decision Memory search, the Executive KPI Engine,
and the Self-Learning recalibration loop have realistic volume to work with
beyond the 5 hand-authored hero incidents in executive/seed_data.py.

No build step / no external data files: this runs at import time and always
produces the same output for a given seed, so it's safe to rely on for tests.
"""

import random
from typing import List, NamedTuple, Optional, Tuple

from contracts import IncidentRecord, CausalChainEntry, Capability, CallStatus, PolicyTier


class _Category(NamedTuple):
    condition_id: str
    label: str
    plant_id: str
    line_id: str
    supplier_id: Optional[str]
    capability: Capability
    base_weight: float
    sample_weight: float  # relative frequency, per documentation/02's 100-record breakdown


# Mirrors the 8 causal conditions seeded in knowledge/causal_graph.py.
# sample_weight distribution approximates documentation/02_Demo_Dataset_and_Digital_Twin.md's
# "Breakdown of Historical Incidents": 42 tolerance/tool-wear, 21 environmental,
# 18 supplier material inclusion, 12 spindle vibration, 7 robot/calibration.
CATEGORIES: List[_Category] = [
    _Category("COND-TOL-DRIFT", "Tolerance drift", "FAC-P04-L2", "Line 2", "SUP-301", Capability.UPDATE_MES, 0.72, 21.0),
    _Category("COND-TOOL-WEAR", "Tool wear", "FAC-P04-L2", "Line 2", None, Capability.UPDATE_MES, 0.63, 21.0),
    _Category("COND-HUMIDITY-SPIKE", "Humidity spike", "FAC-P04-L2", "Line 2", None, Capability.NOTIFY_OPERATOR, 0.55, 21.0),
    _Category("COND-SUPPLIER-BATCH", "Supplier defects", "FAC-P04-L2", "Line 2", "SUP-301", Capability.RESERVE_INVENTORY, 0.66, 9.0),
    _Category("COND-MATERIAL-MISMATCH", "Material mismatch", "FAC-P04-L1", "Line 1", "SUP-303", Capability.RESERVE_INVENTORY, 0.61, 9.0),
    _Category("COND-MACHINE-VIBRATION", "Machine vibration", "FAC-P04-L2", "Line 2", "SUP-302", Capability.SCHEDULE_MAINTENANCE, 0.58, 12.0),
    _Category("COND-CALIBRATION-DRIFT", "Calibration drift", "FAC-P04-L2", "Line 2", None, Capability.SCHEDULE_MAINTENANCE, 0.60, 4.0),
    _Category("COND-SHIPPING-DELAY", "Shipping delay", "FAC-P04-WH", "Warehouse", "SUP-305", Capability.CREATE_PURCHASE_ORDER, 0.55, 3.0),
]

# (policy_tier, weight, confidence_range, mttr_min_range)
_TIER_PROFILES = [
    (PolicyTier.AUTONOMOUS, 0.50, (0.85, 0.98), (5.0, 25.0)),
    (PolicyTier.APPROVAL_REQUIRED, 0.35, (0.80, 0.96), (20.0, 90.0)),
    (PolicyTier.EXECUTIVE_APPROVAL, 0.15, (0.78, 0.97), (60.0, 240.0)),
]

_APPROVERS = ["usr_mfg_mgr_bangalore", "usr_qa_lead_bangalore", "usr_plant_supervisor"]
_MONTH_DAYS = [(m, d) for m in range(1, 7) for d in (3, 8, 14, 19, 24, 28)]  # Jan-Jun 2026, pre-hero-incident history


def _pick_tier(rng: random.Random) -> Tuple[PolicyTier, float, Tuple[float, float], Tuple[float, float]]:
    roll = rng.random()
    cumulative = 0.0
    for profile in _TIER_PROFILES:
        cumulative += profile[1]
        if roll <= cumulative:
            return profile
    return _TIER_PROFILES[-1]


def generate_historical_incidents(count: int = 95, seed: int = 42) -> List[IncidentRecord]:
    """Generate `count` deterministic historical IncidentRecords across all 8
    Nova Motors incident categories. Same `seed` always yields the same
    incidents (order and content), so tests can assert on exact counts."""
    rng = random.Random(seed)
    records: List[IncidentRecord] = []
    category_sequence = rng.choices(CATEGORIES, weights=[c.sample_weight for c in CATEGORIES], k=count)

    for i in range(count):
        category = category_sequence[i]
        tier, _, confidence_range, mttr_range = _pick_tier(rng)

        month, day = _MONTH_DAYS[i % len(_MONTH_DAYS)]
        hour = 6 + (i % 12)
        minute = (i * 7) % 60
        detected_at = f"2026-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"

        mttr_min = round(rng.uniform(*mttr_range), 1)
        resolved_hour = hour
        resolved_minute = minute + int(mttr_min)
        while resolved_minute >= 60:
            resolved_minute -= 60
            resolved_hour = (resolved_hour + 1) % 24
        resolved_at = f"2026-{month:02d}-{day:02d}T{resolved_hour:02d}:{resolved_minute:02d}:00Z"

        confidence = round(rng.uniform(*confidence_range), 2)
        weight = round(min(1.0, max(0.05, category.base_weight + rng.uniform(-0.15, 0.15))), 2)

        estimated_downtime = round(mttr_min * rng.uniform(1.5, 3.5), 1)
        estimated_cost = round(rng.uniform(800.0, 40000.0), 2)
        actual_cost = round(estimated_cost * rng.uniform(0.2, 0.9), 2)

        if tier == PolicyTier.AUTONOMOUS:
            approved_by = None
            recommendation_accepted = None
        else:
            approved_by = rng.choice(_APPROVERS) if tier == PolicyTier.APPROVAL_REQUIRED else "exec_vp_operations"
            recommendation_accepted = rng.random() > 0.15

        records.append(
            IncidentRecord(
                incident_id=f"INC-GEN-{i + 1:04d}",
                plant_id=category.plant_id,
                line_id=category.line_id,
                detected_at=detected_at,
                resolved_at=resolved_at,
                final_state="Resolved",
                causal_chain=[
                    CausalChainEntry(
                        condition_id=category.condition_id,
                        description=f"{category.label} on {category.line_id}",
                        weight=weight,
                        evidence_path=[f"Historical telemetry -> {category.label} pattern match"]
                    )
                ],
                confidence=confidence,
                alternatives=[],
                policy_tier=tier,
                approved_by=approved_by,
                recommendation_accepted=recommendation_accepted,
                capability_invoked=category.capability,
                capability_status=CallStatus.SUCCEEDED,
                supplier_id=category.supplier_id,
                estimated_cost_usd=estimated_cost,
                actual_cost_usd=actual_cost,
                estimated_downtime_min=estimated_downtime,
                actual_downtime_min=mttr_min,
            )
        )

    return records
