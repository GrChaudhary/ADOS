"""
Phase 4B Self-Learning, Memory RAG, & Autonomy Optimization Demonstration Script.
Demonstrates: Decision Memory Search -> Learning Engine Recalibration -> Memory RAG Agent Reasoning -> Autonomy Policy Optimization
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts import DecisionMemoryQuery
from knowledge import DecisionMemoryIndex, LearningEngine, CausalGraph, KnowledgeGraph
from agents import CausalIsolationAgent
from agents.sdk import IncidentContext, StageInput
from executive import AutonomyPolicyOptimizer


def run_demo():
    print("=" * 80)
    print("      ADOS Phase 4B: Self-Learning Engine & Autonomous Optimization Suite")
    print("=" * 80)

    # 1. Initialize Stores & Engines
    index = DecisionMemoryIndex()
    learning = LearningEngine()
    optimizer = AutonomyPolicyOptimizer()

    # STEP 1: Decision Memory Query & Search
    print("\n--- 1. Decision Memory Search (Historical Precedents) ---")
    query = DecisionMemoryQuery(defectType="dimensional fault", plantId="FAC-P1-L3", limit=3)
    search_res = index.search(query)
    print(f"Query: DefectType='{query.defect_type}', PlantId='{query.plant_id}'")
    print(f"Matches Found: {search_res.total_matches} historical incident records")
    for idx, rec in enumerate(search_res.records, start=1):
        rel_score = search_res.relevance_scores[idx - 1]
        print(f"   [{idx}] ID: {rec.incident_id} | FinalState: {rec.final_state} | MTTR: {rec.actual_downtime_min} min | Relevance: {rel_score}")

    # STEP 2: Self-Learning Engine & Batch Recalibration
    print("\n--- 2. Learning Engine: Causal Graph Recalibration ---")
    print("Replaying historical audit records to adjust causal edge weights...")
    replay_summary = learning.replay_audit_trail(learning_rate=0.08)
    print(f"Audit Records Processed: {replay_summary.records_processed} | Edges Recalibrated: {replay_summary.edges_updated}")
    print("Weight Recalibration Log:")
    for adj in replay_summary.weight_adjustments:
        print(f"   • Incident {adj['incident_id']} ({adj['condition_id']} -> {adj['outcome_id']}): {adj['previous_weight']} ==> {adj['new_weight']} (Delta: +{adj['delta']})")

    # STEP 3: Memory-Augmented Agent RAG Execution
    print("\n--- 3. Memory-Augmented Agent RAG Execution ---")
    causal_agent = CausalIsolationAgent(memory_index=index)
    context = IncidentContext(
        incident_id="INC-2026-0723-999",
        plant_id="FAC-P1-L3",
        line_id="Line 3",
        severity="HIGH"
    )
    stage_in = StageInput(stage_name="Reasoning", payload={"defect_type": "dimensional fault"})
    out, env = causal_agent.run(context, stage_in)

    print(f"Agent Execution Result: Primary Root Cause = '{out.result['primary_root_cause']}'")
    print(f"Confidence (Boosted by Memory RAG): {out.confidence} (Original Base Prior: 0.72)")
    print("Evidence Citation List:")
    for ev in out.evidence:
        print(f"   • [{ev.source_type}] {ev.reference_id}: {ev.description}")

    # STEP 4: Executive Autonomy Policy Optimizer
    print("\n--- 4. Executive Autonomy Policy Optimizer ---")
    print("Evaluating historical decision clusters for Tier 0 autonomous promotion...")
    candidates = optimizer.evaluate_promotion_candidates()
    print(f"Evaluated {len(candidates)} decision categories:")
    for cand in candidates:
        status_label = "[ELIGIBLE FOR TIER 0]" if cand.is_eligible else "[REQUIRES MORE DATA]"
        print(f"\n{status_label} {cand.decision_class_name}")
        print(f"   Candidate ID: {cand.candidate_id} | Condition: {cand.condition_id}")
        print(f"   Sample Volume: {cand.sample_volume} incidents | Operator Acceptance: {round(cand.operator_acceptance_rate*100, 1)}% | Avg Confidence: {cand.avg_confidence}")
        print(f"   Rationale: {cand.promotion_rationale}")
        print("   Enforced Safety Guardrails:")
        for guard in cand.safety_guardrails:
            print(f"     -> {guard}")

    print("\n" + "=" * 80)
    print("      SUCCESS: Phase 4B Self-Learning Suite Executed Cleanly!")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
