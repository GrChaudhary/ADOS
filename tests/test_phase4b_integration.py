"""
Unit & Integration tests for Phase 4B:
- Decision Memory Index & Search
- Self-Learning Engine & Causal Recalibration Loop
- Memory-Augmented Agent RAG Precedent Retrieval
- Executive Autonomy Policy Optimizer
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from contracts import DecisionMemoryQuery, IncidentRecord
from knowledge import (
    DecisionMemoryIndex, LearningEngine, CausalGraph, KnowledgeGraph
)
from agents import CausalIsolationAgent
from agents.sdk import IncidentContext, StageInput, DecisionMemoryRAG
from executive import AutonomyPolicyOptimizer, INCIDENT_RECORDS_SEED


@pytest.fixture
def memory_index():
    return DecisionMemoryIndex()


@pytest.fixture
def learning_engine():
    return LearningEngine()


@pytest.fixture
def autonomy_optimizer():
    return AutonomyPolicyOptimizer()


# --- 1. Decision Memory Index & Search Tests ---

def test_decision_memory_index_search(memory_index):
    query = DecisionMemoryQuery(defectType="dimensional fault", limit=5)
    res = memory_index.search(query)

    assert res.total_matches > 0
    assert len(res.records) > 0
    assert any(r.incident_id == "INC-2026-0701-001" for r in res.records)


# --- 2. Learning Engine Recalibration Tests ---

def test_learning_engine_recalibration(learning_engine):
    summary = learning_engine.replay_audit_trail(learning_rate=0.08)

    # 5 hero incidents + 95 deterministically generated historical incidents
    assert summary.records_processed == 100
    assert summary.edges_updated > 0
    assert len(summary.weight_adjustments) > 0
    assert summary.weight_adjustments[0]["new_weight"] > summary.weight_adjustments[0]["previous_weight"]


# --- 3. Memory RAG Agent Retrieval Tests ---

def test_agent_memory_rag_retrieval(memory_index):
    agent = CausalIsolationAgent(memory_index=memory_index)
    context = IncidentContext(incident_id="INC-NEW-0099", plant_id="FAC-P1-L3", line_id="Line 3")
    stage_in = StageInput(stage_name="Reasoning", payload={"defect_type": "dimensional fault"})

    output, envelope = agent.run(context, stage_in)

    # Verify memory precedent evidence attached
    precedent_evidence = [e for e in output.evidence if e.source_type == "PRECEDENT"]
    assert len(precedent_evidence) > 0
    assert output.confidence > 0.72  # Boosted by precedents!


# --- 4. Autonomy Policy Optimizer Tests ---

def test_autonomy_policy_optimizer(autonomy_optimizer):
    candidates = autonomy_optimizer.evaluate_promotion_candidates()

    assert len(candidates) > 0
    eligible_candidates = [c for c in candidates if c.is_eligible]
    assert len(eligible_candidates) > 0
    top_candidate = eligible_candidates[0]
    assert top_candidate.target_tier == "TIER_0_AUTONOMOUS"
    assert len(top_candidate.safety_guardrails) > 0
