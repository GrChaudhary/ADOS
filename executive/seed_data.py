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
    ),

    # Record 6: Tier 0 CNC Parameter Shift (Line 2, Tool Wear)
    IncidentRecord(
        incident_id="INC-2026-0718-035",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-18T08:30:00Z",
        resolved_at="2026-07-18T08:38:00Z",  # 8 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOOL-WEAR",
                description="CNC-103 cutting tool wear detected",
                weight=0.68,
                evidence_path=["Vibration Telemetry -> Tool Thickness Sensor -> Micro-Deviation"]
            )
        ],
        confidence=0.92,
        alternatives=[
            {"option_id": "OPT-1-PARAM-SHIFT", "name": "Feed Rate & Speed Compensation", "estimated_cost_usd": 150.0, "downtime_minutes": 8.0, "quality_risk_score": 0.05, "overall_score": 0.94, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=800.0,
        actual_cost_usd=150.0,
        estimated_downtime_min=20.0,
        actual_downtime_min=8.0
    ),

    # Record 7: Tier 0 Climate Control Adjustment (Line 1, Humidity Spike)
    IncidentRecord(
        incident_id="INC-2026-0720-041",
        plant_id="FAC-P04-L1",
        line_id="Line 1",
        detected_at="2026-07-20T14:15:00Z",
        resolved_at="2026-07-20T14:30:00Z",  # 15 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-HUMIDITY-SPIKE",
                description="Line 1 climate control humidity spike (>65%)",
                weight=0.74,
                evidence_path=["Ambient Sensors -> Humidity Monitor -> Threshold Trigger"]
            )
        ],
        confidence=0.90,
        alternatives=[
            {"option_id": "OPT-1-HUMIDITY-ADJUST", "name": "HVAC Airflow Rate Correction", "estimated_cost_usd": 120.0, "downtime_minutes": 15.0, "quality_risk_score": 0.02, "overall_score": 0.96, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,
        capability_invoked=Capability.NOTIFY_OPERATOR,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id=None,
        estimated_cost_usd=500.0,
        actual_cost_usd=120.0,
        estimated_downtime_min=15.0,
        actual_downtime_min=15.0
    ),

    # Record 8: Tier 0 CNC Spindle Calibration (Line 2, Calibration Drift)
    IncidentRecord(
        incident_id="INC-2026-0722-048",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-22T09:45:00Z",
        resolved_at="2026-07-22T09:56:00Z",  # 11 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-CALIBRATION-DRIFT",
                description="CNC-102 precision spindle alignment drift",
                weight=0.81,
                evidence_path=["Laser CMM -> Spindle Alignment -> Runout Metric Shift"]
            )
        ],
        confidence=0.93,
        alternatives=[
            {"option_id": "OPT-1-SPINDLE-RECAL", "name": "Active Spindle Offset Injection", "estimated_cost_usd": 250.0, "downtime_minutes": 11.0, "quality_risk_score": 0.06, "overall_score": 0.92, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=1200.0,
        actual_cost_usd=250.0,
        estimated_downtime_min=30.0,
        actual_downtime_min=11.0
    ),

    # Record 9: Tier 0 Valve Adjustment (Line 1, Resonance Vibration)
    IncidentRecord(
        incident_id="INC-2026-0724-052",
        plant_id="FAC-P04-L1",
        line_id="Line 1",
        detected_at="2026-07-24T16:10:00Z",
        resolved_at="2026-07-24T16:19:00Z",  # 9 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MACHINE-VIBRATION",
                description="Low-frequency resonance on Line 1 transfer bed",
                weight=0.62,
                evidence_path=["Bed Acoustic Sensor -> Spectral Peaks -> Resonance Alarm"]
            )
        ],
        confidence=0.88,
        alternatives=[
            {"option_id": "OPT-1-VALVE-ADJUST", "name": "Pneumatic Bed Damper Valve Adjustment", "estimated_cost_usd": 90.0, "downtime_minutes": 9.0, "quality_risk_score": 0.03, "overall_score": 0.95, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id=None,
        estimated_cost_usd=400.0,
        actual_cost_usd=90.0,
        estimated_downtime_min=10.0,
        actual_downtime_min=9.0
    ),

    # Record 10: Tier 0 Lubrication Override (Line 2, Early Tool Wear)
    IncidentRecord(
        incident_id="INC-2026-0726-059",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-07-26T11:20:00Z",
        resolved_at="2026-07-26T11:26:00Z",  # 6 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-TOOL-WEAR",
                description="Early CNC tool friction warning",
                weight=0.70,
                evidence_path=["Coolant Flowmeter -> Temperature -> Thermal Warning"]
            )
        ],
        confidence=0.91,
        alternatives=[
            {"option_id": "OPT-1-LUBE-INCREASE", "name": "Friction Compensation Coolant Flow Override", "estimated_cost_usd": 80.0, "downtime_minutes": 6.0, "quality_risk_score": 0.04, "overall_score": 0.97, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.AUTONOMOUS,
        approved_by=None,
        recommendation_accepted=None,
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=500.0,
        actual_cost_usd=80.0,
        estimated_downtime_min=12.0,
        actual_downtime_min=6.0
    ),

    # Record 11: Tier 1 Approved Part Substitution (Line 1, Casting Porosity)
    IncidentRecord(
        incident_id="INC-2026-0728-064",
        plant_id="FAC-P04-L1",
        line_id="Line 1",
        detected_at="2026-07-28T10:30:00Z",
        resolved_at="2026-07-28T11:10:00Z",  # 40 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-SUPPLIER-BATCH",
                description="Titan Metals casting porosity warning in body casings",
                weight=0.76,
                evidence_path=["QA Scans -> Casing Porosity -> Material Rejection Log"]
            )
        ],
        confidence=0.92,
        alternatives=[
            {"option_id": "OPT-1-SUBSTITUTE-PART", "name": "Switch to Alternative Supplier stock (MH-9200)", "estimated_cost_usd": 1800.0, "downtime_minutes": 40.0, "quality_risk_score": 0.04, "overall_score": 0.91, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_mfg_mgr_bangalore",
        recommendation_accepted=True,
        capability_invoked=Capability.RESERVE_INVENTORY,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=3800.0,
        actual_cost_usd=1800.0,
        estimated_downtime_min=90.0,
        actual_downtime_min=40.0
    ),

    # Record 12: Tier 1 Approved Lamination Verification (Line 1, Material Thickness)
    IncidentRecord(
        incident_id="INC-2026-0730-071",
        plant_id="FAC-P04-L1",
        line_id="Line 1",
        detected_at="2026-07-30T13:40:00Z",
        resolved_at="2026-07-30T14:28:00Z",  # 48 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MATERIAL-MISMATCH",
                description="Lamination thickness deviation alert",
                weight=0.68,
                evidence_path=["In-line Thickness Sensor -> Gauge Readings -> Threshold Deviation"]
            )
        ],
        confidence=0.87,
        alternatives=[
            {"option_id": "OPT-1-LAMINATION-CHECK", "name": "Manual Micrometer Core Thickness Check", "estimated_cost_usd": 150.0, "downtime_minutes": 48.0, "quality_risk_score": 0.08, "overall_score": 0.89, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_qa_lead_bangalore",
        recommendation_accepted=True,
        capability_invoked=Capability.NOTIFY_OPERATOR,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-303",
        estimated_cost_usd=2200.0,
        actual_cost_usd=150.0,
        estimated_downtime_min=60.0,
        actual_downtime_min=48.0
    ),

    # Record 13: Tier 1 Approved Maintenance Window (Line 2, Axis 3 Belt Wear)
    IncidentRecord(
        incident_id="INC-2026-0801-080",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-08-01T15:00:00Z",
        resolved_at="2026-08-01T15:55:00Z",  # 55 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-CALIBRATION-DRIFT",
                description="Axis 3 belt tension wear detected on ROB-402",
                weight=0.79,
                evidence_path=["Belt Encoder -> Slip Metric -> Slip Anomaly Alarm"]
            )
        ],
        confidence=0.90,
        alternatives=[
            {"option_id": "OPT-1-MAINT-SCHED", "name": "Immediate Belt Tension Adjustment & Re-align", "estimated_cost_usd": 400.0, "downtime_minutes": 55.0, "quality_risk_score": 0.03, "overall_score": 0.92, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_plant_supervisor",
        recommendation_accepted=True,
        capability_invoked=Capability.SCHEDULE_MAINTENANCE,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-302",
        estimated_cost_usd=2500.0,
        actual_cost_usd=400.0,
        estimated_downtime_min=120.0,
        actual_downtime_min=55.0
    ),

    # Record 14: Tier 1 Approved PO Routing Adjustment (Warehouse, Shipping Delay)
    IncidentRecord(
        incident_id="INC-2026-0803-085",
        plant_id="FAC-P04-WH",
        line_id="Warehouse",
        detected_at="2026-08-03T11:00:00Z",
        resolved_at="2026-08-03T12:10:00Z",  # 70 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-SHIPPING-DELAY",
                description="Gothenburg port shipping delay from SKF Industrial (SUP-305)",
                weight=0.72,
                evidence_path=["Logistics API -> Transit Status -> Delay Exception"]
            )
        ],
        confidence=0.86,
        alternatives=[
            {"option_id": "OPT-1-ADJUST-PO", "name": "Fallback Supplier PO Re-routing (SUP-302)", "estimated_cost_usd": 850.0, "downtime_minutes": 70.0, "quality_risk_score": 0.02, "overall_score": 0.88, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_mfg_mgr_bangalore",
        recommendation_accepted=True,
        capability_invoked=Capability.CREATE_PURCHASE_ORDER,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-305",
        estimated_cost_usd=3000.0,
        actual_cost_usd=850.0,
        estimated_downtime_min=180.0,
        actual_downtime_min=70.0
    ),

    # Record 15: Tier 1 Approved Sensor Calibration (Line 1, Calibration Drift)
    IncidentRecord(
        incident_id="INC-2026-0805-091",
        plant_id="FAC-P04-L1",
        line_id="Line 1",
        detected_at="2026-08-05T09:30:00Z",
        resolved_at="2026-08-05T10:08:00Z",  # 38 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-CALIBRATION-DRIFT",
                description="Line 1 lamination alignment sensor out of calibration",
                weight=0.75,
                evidence_path=["In-line Spectrometer -> Laser Deviation -> Self-Test Failure"]
            )
        ],
        confidence=0.89,
        alternatives=[
            {"option_id": "OPT-1-CALIBRATE-SENSOR", "name": "Operator On-Site Optical Sensor Recalibration", "estimated_cost_usd": 120.0, "downtime_minutes": 38.0, "quality_risk_score": 0.05, "overall_score": 0.93, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.APPROVAL_REQUIRED,
        approved_by="usr_plant_supervisor",
        recommendation_accepted=True,
        capability_invoked=Capability.NOTIFY_OPERATOR,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id=None,
        estimated_cost_usd=1500.0,
        actual_cost_usd=120.0,
        estimated_downtime_min=45.0,
        actual_downtime_min=38.0
    ),

    # Record 16: Tier 2 Exec Approved Line Re-routing (Line 2, Joint Failure)
    IncidentRecord(
        incident_id="INC-2026-0808-102",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-08-08T14:00:00Z",
        resolved_at="2026-08-08T16:00:00Z",  # 120 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MACHINE-VIBRATION",
                description="Structural robot weld joint failure on body cell ROB-402",
                weight=0.91,
                evidence_path=["Weld Joint Telemetry -> Strain Gauge -> Severe Fracture Warning"]
            )
        ],
        confidence=0.95,
        alternatives=[
            {"option_id": "OPT-1-REROUTE-LINE", "name": "Assembly Rerouting body frames to Line 1 Body Cell", "estimated_cost_usd": 15000.0, "downtime_minutes": 120.0, "quality_risk_score": 0.04, "overall_score": 0.90, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
        approved_by="exec_vp_operations",
        recommendation_accepted=True,
        capability_invoked=Capability.SCHEDULE_MAINTENANCE,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-302",
        estimated_cost_usd=40000.0,
        actual_cost_usd=15000.0,
        estimated_downtime_min=300.0,
        actual_downtime_min=120.0
    ),

    # Record 17: Tier 2 Exec Approved Supplier Override (Line 1, Steel Porosity)
    IncidentRecord(
        incident_id="INC-2026-0810-110",
        plant_id="FAC-P04-L1",
        line_id="Line 1",
        detected_at="2026-08-10T08:00:00Z",
        resolved_at="2026-08-10T11:00:00Z",  # 180 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MATERIAL-MISMATCH",
                description="Bulk steel lot lamination impurities across Stator batch",
                weight=0.88,
                evidence_path=["Metallurgy Lab -> Spectro Analysis -> Density Defect Report"]
            )
        ],
        confidence=0.94,
        alternatives=[
            {"option_id": "OPT-1-SUPPLIER-OVERRIDE", "name": "Emergency Contract Override to pre-approved supplier (EuroSteels)", "estimated_cost_usd": 18000.0, "downtime_minutes": 180.0, "quality_risk_score": 0.03, "overall_score": 0.89, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
        approved_by="exec_vp_operations",
        recommendation_accepted=True,
        capability_invoked=Capability.RESERVE_INVENTORY,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-303",
        estimated_cost_usd=50000.0,
        actual_cost_usd=18000.0,
        estimated_downtime_min=420.0,
        actual_downtime_min=180.0
    ),

    # Record 18: Tier 2 Exec Approved Voltage Sag Preemption (Line 2, sag)
    IncidentRecord(
        incident_id="INC-2026-0812-118",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-08-12T16:20:00Z",
        resolved_at="2026-08-12T17:55:00Z",  # 95 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MACHINE-VIBRATION",
                description="Severe sub-station voltage sag at CNC-102 cell",
                weight=0.82,
                evidence_path=["Microgrid Feed -> Power Quality Monitor -> Sag Event Trigger"]
            )
        ],
        confidence=0.89,
        alternatives=[
            {"option_id": "OPT-1-POWER-REROUTE", "name": "Plant Microgrid Power Re-routing & CNC Cycle Hold", "estimated_cost_usd": 5500.0, "downtime_minutes": 95.0, "quality_risk_score": 0.05, "overall_score": 0.92, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
        approved_by="exec_vp_operations",
        recommendation_accepted=True,
        capability_invoked=Capability.UPDATE_MES,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-301",
        estimated_cost_usd=25000.0,
        actual_cost_usd=5500.0,
        estimated_downtime_min=180.0,
        actual_downtime_min=95.0
    ),

    # Record 19: Tier 2 Exec Approved Supply Chain Logistics Routing (Warehouse, delays)
    IncidentRecord(
        incident_id="INC-2026-0815-125",
        plant_id="FAC-P04-WH",
        line_id="Warehouse",
        detected_at="2026-08-15T09:00:00Z",
        resolved_at="2026-08-15T11:30:00Z",  # 150 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-SHIPPING-DELAY",
                description="Global logistics shipping delay due to Rotterdam port strike",
                weight=0.85,
                evidence_path=["Supply Chain API -> Carrier Logs -> Force Majeure Exception"]
            )
        ],
        confidence=0.91,
        alternatives=[
            {"option_id": "OPT-1-AIR-FREIGHT", "name": "Emergency Air Freight Re-routing for Bearing assemblies", "estimated_cost_usd": 22000.0, "downtime_minutes": 150.0, "quality_risk_score": 0.01, "overall_score": 0.87, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
        approved_by="exec_vp_operations",
        recommendation_accepted=True,
        capability_invoked=Capability.CREATE_PURCHASE_ORDER,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-305",
        estimated_cost_usd=60000.0,
        actual_cost_usd=22000.0,
        estimated_downtime_min=360.0,
        actual_downtime_min=150.0
    ),

    # Record 20: Tier 2 Exec Approved Servo Replacement (Line 2, gear runout)
    IncidentRecord(
        incident_id="INC-2026-0818-132",
        plant_id="FAC-P04-L2",
        line_id="Line 2",
        detected_at="2026-08-18T10:15:00Z",
        resolved_at="2026-08-18T12:05:00Z",  # 110 min MTTR
        final_state="Resolved",
        causal_chain=[
            CausalChainEntry(
                condition_id="COND-MACHINE-VIBRATION",
                description="Line 2 CNC-102 motor housing robot Axis 2 severe gear runout",
                weight=0.93,
                evidence_path=["Acoustic Telemetry -> Sensor Array -> Resonance Fracture Warning"]
            )
        ],
        confidence=0.96,
        alternatives=[
            {"option_id": "OPT-1-EMERGENCY-REPLACE", "name": "Immediate Axis 2 Servo Replacement & Calibration", "estimated_cost_usd": 14000.0, "downtime_minutes": 110.0, "quality_risk_score": 0.04, "overall_score": 0.91, "recommendation": "TOP_PICK"},
        ],
        policy_tier=PolicyTier.EXECUTIVE_APPROVAL,
        approved_by="exec_vp_operations",
        recommendation_accepted=True,
        capability_invoked=Capability.SCHEDULE_MAINTENANCE,
        capability_status=CallStatus.SUCCEEDED,
        supplier_id="SUP-302",
        estimated_cost_usd=45000.0,
        actual_cost_usd=14000.0,
        estimated_downtime_min=240.0,
        actual_downtime_min=110.0
    )
]

INCIDENT_RECORDS_SEED: List[IncidentRecord] = HERO_INCIDENTS + generate_historical_incidents(count=200)

