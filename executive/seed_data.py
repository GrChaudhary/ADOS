"""
Seed dataset of IncidentRecord fixtures for local development and testing of
Executive Intelligence (Phase 3B).

Nova Motors Plant 04 (Bangalore, Karnataka) demo dataset
(documentation/02_Demo_Dataset_and_Digital_Twin.md): 5 "hero" incidents
hand-authored for the narrative demo flow, plus ~95 generated historical
incidents (executive/incident_generator.py) spanning all 8 incident
categories, giving Decision Memory / the Knowledge Graph realistic volume
for search, KPI, and recalibration demos.
"""

from typing import List
from contracts import IncidentRecord, CausalChainEntry, Capability, CallStatus, PolicyTier
from .incident_generator import generate_historical_incidents

HERO_INCIDENTS: List[IncidentRecord] = [
    # Record 1: Tier 0 Autonomous Parameter Compensation (Line 2, Motor Housing)
    IncidentRecord(
        incident_id="INC-2026-0701-001",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-01T08:15:00Z",
        resolved_at="2026-07-01T08:27:00Z",  # 12 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOL-DRIFT",
                description="Tolerance drift on Line 2 CNC-102",
                weight=0.72,
                evidence_path=["CNC Telemetry -> Vibration -> Bore Measurement Deviation"]
            )
        ],
        confidence=0.94,
        alternatives=[
            {"option_id": "OPT-1-PARAMETER-ADJUST", "name": "CNC-102 Parameter Compensation", "estimated_cost_usd": 350.0, "downtime_minutes": 12.0, "quality_risk_score": 0.08, "overall_score": 0.92, "recommendation": "TOP_PICK"},
            {"option_id": "OPT-2-REPLACE-TOOLING", "name": "Replace Tooling", "estimated_cost_usd": 14000.0, "downtime_minutes": 180.0, "quality_risk_score": 0.02, "overall_score": 0.55, "recommendation": "FEASIBLE"},
        ],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,  # Null for Tier 0
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=1200.0,
        actual_cost_usd=350.0,
        estimated_downtime_min=45.0,
        actual_downtime_min=12.0
    ),

    # Record 2: Tier 1 Approved Supplier Switch (Line 2, Motor Housing, PrecisionCast)
    IncidentRecord(
        incident_id="INC-2026-0703-004",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-03T10:00:00Z",
        resolved_at="2026-07-03T10:35:00Z",  # 35 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-SUPPLIER-BATCH",
                description="Titan Metals Lot #B-409 casting porosity requiring supplier switch approval",
                weight=0.75,
                evidence_path=["Incoming QA -> Batch Lot B-409 -> Casting Porosity Log"]
            )
        ],
        confidence=0.91,
        alternatives=[
            {"option_id": "OPT-2-PART-SUBSTITUTION", "name": "Switch to PrecisionCast GmbH (MH-8820-PC stock)", "estimated_cost_usd": 2250.0, "downtime_minutes": 35.0, "quality_risk_score": 0.05, "overall_score": 0.90, "recommendation": "TOP_PICK"},
            {"option_id": "OPT-3-WAIT-FOR-RESUPPLY", "name": "Wait for Titan Metals Resupply", "estimated_cost_usd": 8500.0, "downtime_minutes": 7200.0, "quality_risk_score": 0.02, "overall_score": 0.52, "recommendation": "FEASIBLE"},
        ],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_mfg_mgr_bangalore",
        recommendation_accepted=True,  # Approved as recommended
        capability_invoked=Capability.RESERVE_INVENTORY,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=4500.0,
        actual_cost_usd=2250.0,
        estimated_downtime_min=120.0,
        actual_downtime_min=35.0
    ),

    # Record 3: Tier 1 Rejected/Modified Recommendation (Line 1, Stator Core material mismatch)
    IncidentRecord(
        incident_id="INC-2026-0705-012",
        plant_id="FAC-P04-L1",
        line_id="Line 1",
        detected_at="2026-07-05T14:20:00Z",
        resolved_at="2026-07-05T15:10:00Z",  # 50 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MATERIAL-MISMATCH",
                description="Stator core material certification mismatch",
                weight=0.55,
                evidence_path=["Incoming QA -> Material Certification Cross-Check Failure"]
            )
        ],
        confidence=0.65,
        alternatives=[
            {"option_id": "OPT-1-CERT-REVERIFY", "name": "Re-verify Material Certification", "estimated_cost_usd": 1500.0, "downtime_minutes": 60.0, "quality_risk_score": 0.03, "overall_score": 0.81, "recommendation": "TOP_PICK"},
            {"option_id": "OPT-2-MANUAL-INSPECTION", "name": "Manual Lamination Inspection", "estimated_cost_usd": 200.0, "downtime_minutes": 180.0, "quality_risk_score": 0.15, "overall_score": 0.55, "recommendation": "FEASIBLE"},
        ],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_mfg_mgr_bangalore",
        recommendation_accepted=False,  # Operator rejected automated cert override and did manual inspection
        capability_invoked=Capability.NOTIFY_OPERATOR,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-303",
        estimated_cost_usd=2000.0,
        actual_cost_usd=1800.0,
        estimated_downtime_min=60.0,
        actual_downtime_min=50.0
    ),

    # Record 4: Tier 2 Executive Approved Re-routing (Line 2, ROB-401 bearing failure)
    IncidentRecord(
        incident_id="INC-2026-0710-022",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-10T09:00:00Z",
        resolved_at="2026-07-10T10:45:00Z",  # 105 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MACHINE-VIBRATION",
                description="Major ROB-401 bearing assembly failure",
                weight=0.89,
                evidence_path=["Vibration Telemetry -> Acoustic Sensor -> Severe Bearing Runout"]
            )
        ],
        confidence=0.96,
        alternatives=[
            {"option_id": "OPT-1-REPLACE-AND-REROUTE", "name": "Immediate Bearing Replacement & Reroute", "estimated_cost_usd": 12500.0, "downtime_minutes": 105.0, "quality_risk_score": 0.04, "overall_score": 0.88, "recommendation": "TOP_PICK"},
            {"option_id": "OPT-2-LINE-STOP", "name": "Immediate Line Stop without Re-route", "estimated_cost_usd": 45000.0, "downtime_minutes": 240.0, "quality_risk_score": 0.01, "overall_score": 0.40, "recommendation": "FEASIBLE"},
        ],
        policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
        approved_by="exec_vp_operations",
        recommendation_accepted=True,
        capability_invoked=Capability.SCHEDULE_MAINTENANCE,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-302",
        estimated_cost_usd=35000.0,
        actual_cost_usd=12500.0,
        estimated_downtime_min=240.0,
        actual_downtime_min=105.0
    ),

    # Record 5: Tier 0 Autonomous Parameter Compensation (Line 2, Motor Housing)
    IncidentRecord(
        incident_id="INC-2026-0715-030",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-15T11:00:00Z",
        resolved_at="2026-07-15T11:10:00Z",  # 10 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOL-DRIFT",
                description="Tolerance drift on Line 2 CNC-102",
                weight=0.78,
                evidence_path=["CNC Telemetry -> Spindle Vibration -> Bore Measurement Deviation"]
            )
        ],
        confidence=0.95,
        alternatives=[
            {"option_id": "OPT-1-PARAMETER-ADJUST", "name": "CNC-102 Parameter Compensation", "estimated_cost_usd": 300.0, "downtime_minutes": 10.0, "quality_risk_score": 0.06, "overall_score": 0.95, "recommendation": "TOP_PICK"},
            {"option_id": "OPT-2-PART-SUBSTITUTION", "name": "Switch to PrecisionCast GmbH (MH-8820-PC)", "estimated_cost_usd": 900.0, "downtime_minutes": 38.0, "quality_risk_score": 0.04, "overall_score": 0.76, "recommendation": "FEASIBLE"},
        ],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,  # Tier 0
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=1500.0,
        actual_cost_usd=300.0,
        estimated_downtime_min=30.0,
        actual_downtime_min=10.0
    )
]

INCIDENT_RECORDS_SEED: List[IncidentRecord] = HERO_INCIDENTS + generate_historical_incidents()
