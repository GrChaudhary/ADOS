"""
Comprehensive unit & integration tests for ADOS Phase 3B components:
- KPI Engine & What-If Simulations
- Strategic Recommendation Engine
- Enterprise Decision Intelligence (EDI)
- Predictive Risk Analytics
- Natural Language Executive Copilot
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from contracts import IncidentRecord, PolicyTier
from executive import (
    KPIEngine, RecommendationEngine, EnterpriseDecisionIntelligence,
    PredictiveRiskAnalytics, NLExecutiveCopilot, INCIDENT_RECORDS_SEED
)


@pytest.fixture
def kpi_eng():
    return KPIEngine()


@pytest.fixture
def rec_eng():
    return RecommendationEngine()


@pytest.fixture
def edi_eng():
    return EnterpriseDecisionIntelligence()


@pytest.fixture
def risk_eng():
    return PredictiveRiskAnalytics()


@pytest.fixture
def copilot():
    return NLExecutiveCopilot()


# --- 1. KPI Engine Tests ---

def test_kpi_engine_metrics_derivation(kpi_eng):
    kpis = kpi_eng.compute_kpis()

    # 5 hand-authored hero incidents + 95 deterministically generated
    # historical incidents (executive/incident_generator.py, seed=42).
    assert kpis.total_incidents == 100
    assert kpis.resolved_incidents == 100
    assert kpis.mttr_avg_minutes > 0
    assert kpis.revenue_protected_usd > 0
    assert kpis.autonomy_index == 0.52
    assert kpis.recommendation_acceptance_rate == 0.8542


def test_kpi_engine_what_if_simulation(kpi_eng):
    sim_result = kpi_eng.run_what_if_simulation(target_condition_id="COND-TOL-DRIFT")

    assert "baseline" in sim_result
    assert "simulated" in sim_result
    assert sim_result["simulated"]["autonomy_index"] > sim_result["baseline"]["autonomy_index"]
    assert sim_result["delta"]["mttr_reduction_min"] >= 0


# --- 2. Recommendation Engine Tests ---

def test_recommendation_engine_generation(rec_eng):
    recs = rec_eng.generate_strategic_recommendations()

    assert len(recs) >= 2
    categories = [r.category for r in recs]
    assert "SUPPLIER_REQUALIFICATION" in categories
    assert "AUTONOMY_PROMOTION" in categories
    assert any(r.estimated_annual_savings_usd > 0 for r in recs)


# --- 3. EDI Tests ---

def test_edi_pattern_analysis(edi_eng):
    clusters = edi_eng.analyze_root_cause_clusters()
    assert len(clusters) > 0
    assert clusters[0]["condition_id"] == "COND-TOOL-WEAR"

    variance = edi_eng.analyze_cost_variance()
    assert variance["total_estimated_cost_usd"] > variance["total_actual_cost_usd"]
    assert variance["net_revenue_protected_usd"] > 0

    benchmarks = edi_eng.generate_plant_benchmarks()
    assert "FAC-P04-L2" in benchmarks
    assert benchmarks["FAC-P04-L2"]["autonomy_index"] > 0


# --- 4. Predictive Risk Analytics Tests ---

def test_predictive_risk_evaluation(risk_eng):
    signal = risk_eng.evaluate_line_risk("FAC-P04-L2", "Line 2")

    assert signal.plant_id == "FAC-P04-L2"
    assert signal.line_id == "Line 2"
    assert 0.0 <= signal.risk_score <= 1.0
    assert signal.risk_level in ["CRITICAL", "ELEVATED", "NORMAL"]

    all_signals = risk_eng.get_all_plant_risk_signals()
    assert len(all_signals) >= 3


# --- 5. NL Executive Copilot Tests ---

def test_copilot_kpi_query(copilot):
    resp = copilot.ask("What is our current MTTR and Autonomy Index?")

    assert resp.confidence >= 0.90
    assert "MTTR" in resp.answer
    assert "Autonomy Index" in resp.answer
    assert len(resp.data_citations) > 0


def test_copilot_supplier_query(copilot):
    resp = copilot.ask("Show me supplier resilience metrics for SUP-301")

    assert resp.confidence >= 0.90
    assert "Supplier Resilience" in resp.answer
    assert len(resp.data_citations) > 0


def test_copilot_what_if_query(copilot):
    resp = copilot.ask("What if we automate CNC tolerance drift decisions?")

    assert resp.confidence >= 0.90
    assert "What-If Simulation Results" in resp.answer
    assert "Projected MTTR Reduction" in resp.answer
