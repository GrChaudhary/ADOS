"""
Phase 3B Executive Intelligence Demonstration Script.
Demonstrates: KPI Engine -> What-If Simulation -> Strategic Recommendation Engine -> EDI -> Predictive Risk -> NL Executive Copilot
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from executive import (
    KPIEngine, RecommendationEngine, EnterpriseDecisionIntelligence,
    PredictiveRiskAnalytics, NLExecutiveCopilot
)


def run_demo():
    print("=" * 80)
    print("      ADOS Phase 3B: Executive Intelligence & Strategic Reasoning Suite")
    print("=" * 80)

    # 1. Initialize Executive Engines
    kpi_engine = KPIEngine()
    rec_engine = RecommendationEngine()
    edi_engine = EnterpriseDecisionIntelligence()
    risk_analytics = PredictiveRiskAnalytics()
    copilot = NLExecutiveCopilot(
        kpi_engine=kpi_engine,
        rec_engine=rec_engine,
        edi=edi_engine,
        risk_analytics=risk_analytics
    )

    # STEP 1: Executive KPI Summary
    print("\n--- 1. Executive KPI Engine Summary ---")
    kpis = kpi_engine.compute_kpis()
    print(f"Total Incidents Tracked: {kpis.total_incidents} (Resolved: {kpis.resolved_incidents}, Failed: {kpis.failed_incidents})")
    print(f"Mean Time To Recovery (MTTR): {kpis.mttr_avg_minutes} min (Median: {kpis.mttr_median_minutes} min)")
    print(f"Revenue Protected: ${kpis.revenue_protected_usd:,.2f} (Total Actual Cost: ${kpis.total_actual_cost_usd:,.2f})")
    print(f"Autonomy Index: {round(kpis.autonomy_index * 100, 1)}% executed at Tier 0")
    print(f"Recommendation Acceptance Rate: {round(kpis.recommendation_acceptance_rate * 100, 1)}% approved at Tier 1/2")
    print("Governance Tier Distribution:")
    for tier, cnt in kpis.tier_distribution.items():
        print(f"   • {tier}: {cnt} incidents")

    # STEP 2: Strategic Recommendation Engine
    print("\n--- 2. Strategic Recommendation Engine ---")
    recommendations = rec_engine.generate_strategic_recommendations()
    print(f"Generated {len(recommendations)} Strategic Recommendations:")
    for rec in recommendations:
        print(f"\n[{rec.recommendation_id}] [{rec.impact_level}] {rec.title}")
        print(f"   Category: {rec.category} | Est. Annual Savings: ${rec.estimated_annual_savings_usd:,.2f}")
        print(f"   Summary: {rec.summary}")
        print("   Action Items:")
        for action in rec.action_items:
            print(f"     -> {action}")

    # STEP 3: What-If Simulation
    print("\n--- 3. What-If Autonomy Simulation ---")
    sim = kpi_engine.run_what_if_simulation(target_condition_id="COND-TOL-DRIFT")
    print(f"Simulating Promotion of '{sim['target_condition_id']}' to {sim['promoted_to_tier']} Autonomy:")
    print(f"   Baseline MTTR: {sim['baseline']['mttr_avg_min']} min  -->  Simulated MTTR: {sim['simulated']['mttr_avg_min']} min (Delta: -{sim['delta']['mttr_reduction_min']} min)")
    print(f"   Baseline Autonomy: {round(sim['baseline']['autonomy_index']*100, 1)}%  -->  Simulated Autonomy: {round(sim['simulated']['autonomy_index']*100, 1)}% (Delta: +{sim['delta']['autonomy_increase_pct']}%)")
    print(f"   Additional Revenue Protected: +${sim['delta']['additional_revenue_protected_usd']:,.2f}")

    # STEP 4: Enterprise Decision Intelligence (EDI)
    print("\n--- 4. Enterprise Decision Intelligence (EDI) Pattern Analysis ---")
    clusters = edi_engine.analyze_root_cause_clusters()
    print("Top Root Cause Clusters by Frequency:")
    for c in clusters:
        print(f"   • [{c['condition_id']}] {c['description']} | Count: {c['incident_count']}, Avg Causal Weight: {c['avg_causal_weight']}, Cost: ${c['total_cost_usd']:,.2f}")

    benchmarks = edi_engine.generate_plant_benchmarks()
    print("\nPlant-to-Plant Comparative Benchmarks:")
    for pid, b in benchmarks.items():
        print(f"   • {pid}: {b['incident_count']} incidents | Avg MTTR: {b['avg_mttr_min']} min | Autonomy Index: {round(b['autonomy_index']*100, 1)}% | Cost: ${b['total_cost_usd']:,.2f}")

    # STEP 5: Predictive Risk Analytics
    print("\n--- 5. Predictive Risk Analytics ---")
    risk_signals = risk_analytics.get_all_plant_risk_signals()
    print(f"Active Plant & Line Risk Signals:")
    for s in risk_signals:
        print(f"   • [{s.signal_id}] {s.plant_id} ({s.line_id}): Risk Score {s.risk_score} [{s.risk_level}]")
        print(f"     Driver: {s.primary_risk_driver}")
        print(f"     Mitigation: {s.recommended_mitigation}")

    # STEP 6: Natural Language Executive Copilot Q&A
    print("\n--- 6. Natural Language Executive Copilot Q&A ---")
    sample_queries = [
        "What is our current MTTR and Autonomy Index?",
        "Show me supplier resilience metrics for S-201",
        "What if we automate CNC tolerance drift decisions?",
        "Which manufacturing lines are currently at highest risk?"
    ]

    for q in sample_queries:
        print(f"\nExecutive Question: '{q}'")
        resp = copilot.ask(q)
        print(f"Copilot Confidence: {resp.confidence} | Recommended Chart: {resp.visual_chart_type}")
        print("Response Answer:")
        print(resp.answer)
        print(f"Citations attached: {len(resp.data_citations)} evidence references")

    print("\n" + "=" * 80)
    print("      SUCCESS: Phase 3B Executive Intelligence Suite Executed Cleanly!")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
