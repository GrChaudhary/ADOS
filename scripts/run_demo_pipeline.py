import sys
from pathlib import Path

# Add project root to PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from contracts import EventEnvelope
from knowledge import KnowledgeGraph, CausalGraph, DigitalTwinStore
from agents.sdk import IncidentContext, StageInput
from agents import (
    VisionSpecAgent,
    CADSpecAgent,
    CausalIsolationAgent,
    SubstitutionAgent,
    ParameterAdjustmentAgent,
    ImpactSimulationAgent,
    ReroutingAgent,
    FeedbackCalibrationAgent
)


def run_demo():
    print("=" * 80)
    print("      ADOS Phase 2: Autonomous Defect & Orchestration Reasoning Pipeline")
    print("=" * 80)

    # 1. Initialize L2 Stores & Digital Twin
    kg = KnowledgeGraph(seed=True)
    cg = CausalGraph(seed=True)
    dt = DigitalTwinStore()

    context = IncidentContext(
        incident_id="INC-2026-0722-001",
        plant_id="FAC-P1-L3",
        line_id="Line 3",
        severity="HIGH"
    )
    print(f"\n[INCIDENT STARTED] ID: {context.incident_id} | Plant: {context.plant_id} | Line: {context.line_id}\n")

    # STAGE 1: Perception (Vision & Spec Agent)
    print("--- 1. Perception Stage: Vision & Spec Agent ---")
    vision_agent = VisionSpecAgent()
    stage1_in = StageInput(stage_name="Perception", payload={"vision_data": {"measured_bore_diameter_mm": 45.085}})
    out1, env1 = vision_agent.run(context, stage1_in)
    print(f"Confidence: {out1.confidence}")
    print(f"Result: Defect='{out1.result['defect_type']}', Measured={out1.result['measured_value']}mm, Deviation={out1.result['deviation_mm']}mm")
    print(f"Event Emitted: {env1.event_type} (ProducedBy: {env1.produced_by})")

    # STAGE 2: Understanding (CAD & Spec Comparison Agent)
    print("\n--- 2. Understanding Stage: CAD & Spec Comparison Agent ---")
    cad_agent = CADSpecAgent(knowledge_graph=kg)
    stage2_in = StageInput(stage_name="Reasoning", payload={"part_number": "P-1002", "measured_value": out1.result['measured_value']})
    out2, env2 = cad_agent.run(context, stage2_in)
    print(f"Confidence: {out2.confidence}")
    print(f"Result: IsViolation={out2.result['is_violation']}, Nominal={out2.result['nominal']}mm, Limits={out2.result['tolerance_range']}")

    # STAGE 3: Root Cause Analysis (Causal Isolation Agent)
    print("\n--- 3. Reasoning Stage: Causal Isolation Agent ---")
    causal_agent = CausalIsolationAgent(causal_graph=cg, knowledge_graph=kg)
    stage3_in = StageInput(stage_name="Reasoning", payload={"defect_type": out1.result['defect_type']})
    out3, env3 = causal_agent.run(context, stage3_in)
    print(f"Confidence: {out3.confidence}")
    print(f"Primary Cause: '{out3.result['primary_root_cause']}' (Weight: {out3.result['root_cause_confidence']})")
    print(f"Affected SKUs: {out3.result['affected_products']}")
    print(f"Evidence Count: {len(out3.evidence)} | Rejected Candidate Causes: {len(out3.alternatives)}")

    # STAGE 4A: Candidate Generation (Substitution Agent)
    print("\n--- 4A. Candidate Generation Stage: Substitution Agent ---")
    sub_agent = SubstitutionAgent(knowledge_graph=kg)
    stage4a_in = StageInput(stage_name="CandidateGeneration", payload={"part_number": "P-1002"})
    out4a, env4a = sub_agent.run(context, stage4a_in)
    print(f"Confidence: {out4a.confidence}")
    if out4a.result["has_approved_substitute"]:
        top_sub = out4a.result["top_candidate"]
        print(f"Approved Substitute: Part {top_sub['target_part_number']} ({top_sub['name']}), Stock={top_sub['in_stock_quantity']} units")

    # STAGE 4B: Candidate Generation (Parameter Adjustment Agent)
    print("\n--- 4B. Candidate Generation Stage: Parameter Adjustment Agent ---")
    param_agent = ParameterAdjustmentAgent(digital_twin=dt)
    stage4b_in = StageInput(stage_name="CandidateGeneration", payload={"deviation_mm": out1.result['deviation_mm']})
    out4b, env4b = param_agent.run(context, stage4b_in)
    print(f"Confidence: {out4b.confidence}")
    print(f"Parameter Tuning: Adjust '{out4b.result['parameter_to_adjust']}' by {out4b.result['recommended_compensation']}mm -> Target: {out4b.result['target_value']}mm")

    # STAGE 5: Evaluation & Simulation (Impact Simulation Agent)
    print("\n--- 5. Evaluation Stage: Impact Simulation Agent ---")
    sim_agent = ImpactSimulationAgent()
    stage5_in = StageInput(stage_name="Evaluation", payload={})
    out5, env5 = sim_agent.run(context, stage5_in)
    print(f"Confidence: {out5.confidence}")
    top_opt = out5.result["top_recommendation"]
    print(f"Top Recommendation: [{top_opt['option_id']}] {top_opt['name']} (Cost: ${top_opt['estimated_cost_usd']}, Downtime: {top_opt['downtime_minutes']} min)")

    # STAGE 6: Execution & Soft Reservation (Re-routing Agent)
    print("\n--- 6. Execution Stage: Re-routing Agent ---")
    reroute_agent = ReroutingAgent(digital_twin=dt)
    stage6_in = StageInput(stage_name="Execution", payload={"selected_option": top_opt["option_id"]})
    out6, env6 = reroute_agent.run(context, stage6_in)
    print(f"Confidence: {out6.confidence}")
    print(f"Capacity Reserved on Line 3: {out6.result['capacity_reserved']}")
    print("Execution Plan:")
    for step in out6.result["execution_steps"]:
        print(f"   {step}")

    # STAGE 7: Learning & Calibration (Feedback & Calibration Agent)
    print("\n--- 7. Learning Stage: Feedback & Calibration Agent ---")
    calib_agent = FeedbackCalibrationAgent(causal_graph=cg)
    stage7_in = StageInput(
        stage_name="Learning",
        payload={
            "condition_id": out3.result["primary_condition_id"],
            "outcome_id": "OUT-DIMENSIONAL-FAULT",
            "outcome_verified": True
        }
    )
    out7, env7 = calib_agent.run(context, stage7_in)
    print(f"Confidence: {out7.confidence}")
    print(f"Causal Weight Update: {out7.result['condition_id']} -> Previous: {out7.result['previous_weight']} | Recalibrated: {out7.result['recalibrated_weight']} (Delta: +{out7.result['delta']})")

    print("\n" + "=" * 80)
    print("      SUCCESS: Phase 2 Decision Loop Execution Completed cleanly!")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
