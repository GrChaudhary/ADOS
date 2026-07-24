"""
Seed dataset of IncidentRecord fixtures for local development and testing of Executive Intelligence (Phase 3B).
"""

from typing import List
from contracts import IncidentRecord, CausalChainEntry, Capability, CallStatus, PolicyTier

INCIDENT_RECORDS_SEED: List[IncidentRecord] = [
    # Record 1: Tier 0 Autonomous Parameter Compensation (Line 3, Plant 1)
    IncidentRecord(
        incident_id="INC-2026-0701-001",
        plant_id="FAC-P1-L3",
        line_id="Line 3",
        detected_at="2026-07-01T08:15:00Z",
        resolved_at="2026-07-01T08:27:00Z",  # 12 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOL-DRIFT",
                description="Tolerance drift on Line 3 CNC Spindle",
                weight=0.72,
                evidence_path=["CNC Telemetry -> Vibration -> Bore Measurement Deviation"]
            )
        ],
        confidence=0.94,
        alternatives=[{"option": "Replace Tooling", "cost": 14000.0, "reason": "Excessive downtime"}],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,  # Null for Tier 0
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="S-201",
        estimated_cost_usd=1200.0,
        actual_cost_usd=350.0,
        estimated_downtime_min=45.0,
        actual_downtime_min=12.0
    ),

    # Record 2: Tier 1 Approved Part Substitution (Line 3, Supplier S-201)
    IncidentRecord(
        incident_id="INC-2026-0703-004",
        plant_id="FAC-P1-L3",
        line_id="Line 3",
        detected_at="2026-07-03T10:00:00Z",
        resolved_at="2026-07-03T10:35:00Z",  # 35 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOL-DRIFT",
                description="Tolerance drift requiring manual Z-offset parameter approval",
                weight=0.75,
                evidence_path=["CNC Telemetry -> Tool Offset Deviation Log"]
            )
        ],
        confidence=0.91,
        alternatives=[{"option": "Wait for Supplier Resupply", "cost": 8500.0, "reason": "2-day lead time"}],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_mfg_mgr_detroit",
        recommendation_accepted=True,  # Approved as recommended
        capability_invoked=Capability.RESERVE_INVENTORY,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="S-201",
        estimated_cost_usd=4500.0,
        actual_cost_usd=2250.0,
        estimated_downtime_min=120.0,
        actual_downtime_min=35.0
    ),

    # Record 3: Tier 1 Rejected/Modified Recommendation (Line 4, Plant 1)
    IncidentRecord(
        incident_id="INC-2026-0705-012",
        plant_id="FAC-P1-L4",
        line_id="Line 4",
        detected_at="2026-07-05T14:20:00Z",
        resolved_at="2026-07-05T15:10:00Z",  # 50 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-HUMIDITY-SPIKE",
                description="Ambient humidity spike (>85%)",
                weight=0.55,
                evidence_path=["PLC Sensor -> Environmental Log"]
            )
        ],
        confidence=0.65,
        alternatives=[{"option": "HVAC Recalibration", "cost": 1500.0, "reason": "Requires maintenance technician"}],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_mfg_mgr_detroit",
        recommendation_accepted=False,  # Operator rejected automated parameter override and did manual check
        capability_invoked=Capability.NOTIFY_OPERATOR,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id=None,
        estimated_cost_usd=2000.0,
        actual_cost_usd=1800.0,
        estimated_downtime_min=60.0,
        actual_downtime_min=50.0
    ),

    # Record 4: Tier 2 Executive Approved Re-routing (Plant 2, Line 1)
    IncidentRecord(
        incident_id="INC-2026-0710-022",
        plant_id="FAC-P2-L1",
        line_id="Line 1",
        detected_at="2026-07-10T09:00:00Z",
        resolved_at="2026-07-10T10:45:00Z",  # 105 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOL-DRIFT",
                description="Major CNC Bearing Assembly Failure",
                weight=0.89,
                evidence_path=["Vibration Telemetry -> Acoustic Sensor -> Severe Bearing Runout"]
            )
        ],
        confidence=0.96,
        alternatives=[{"option": "Immediate Line Stop without Re-route", "cost": 45000.0, "reason": "Misses customer delivery deadline"}],
        policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
        approved_by="exec_vp_operations",
        recommendation_accepted=True,
        capability_invoked=Capability.SCHEDULE_MAINTENANCE,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="S-202",
        estimated_cost_usd=35000.0,
        actual_cost_usd=12500.0,
        estimated_downtime_min=240.0,
        actual_downtime_min=105.0
    ),

    # Record 5: Tier 0 Autonomous Parameter Compensation (Line 3, Plant 1)
    IncidentRecord(
        incident_id="INC-2026-0715-030",
        plant_id="FAC-P1-L3",
        line_id="Line 3",
        detected_at="2026-07-15T11:00:00Z",
        resolved_at="2026-07-15T11:10:00Z",  # 10 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOL-DRIFT",
                description="Tolerance drift on Line 3 CNC Spindle",
                weight=0.78,
                evidence_path=["CNC Telemetry -> Spindle Vibration -> Bore Measurement Deviation"]
            )
        ],
        confidence=0.95,
        alternatives=[],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,  # Tier 0
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="S-201",
        estimated_cost_usd=1500.0,
        actual_cost_usd=300.0,
        estimated_downtime_min=30.0,
        actual_downtime_min=10.0
    )
]
