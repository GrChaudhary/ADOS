"""
Comprehensive unit & integration tests for ADOS Phase 2 components:
- Knowledge Graph store & query surface
- Causal Graph store, root-cause ranking & calibration loop
- Digital Twin store & soft reservations
- Agent SDK base contract & EventEnvelope generation
- Full agent roster execution (Vision, Causal, CAD, Substitution, Parameter, Impact, Rerouting, Calibration)
"""

import pytest
from contracts import EventEnvelope, AgentCompletedPayload
from knowledge import (
    KnowledgeGraph, CausalGraph, DigitalTwinStore,
    Specification, Part, Product
)
from agents.sdk import IncidentContext, StageInput
from knowledge.nlu_client import nlu_client
from agents import (
    VisionSpecAgent,
    CausalIsolationAgent,
    CADSpecAgent,
    SubstitutionAgent,
    ParameterAdjustmentAgent,
    ImpactSimulationAgent,
    ReroutingAgent,
    FeedbackCalibrationAgent
)


@pytest.fixture
def kg():
    return KnowledgeGraph(seed=True)


@pytest.fixture
def cg():
    return CausalGraph(seed=True)


@pytest.fixture
def dt():
    return DigitalTwinStore()


@pytest.fixture
def context():
    return IncidentContext(
        incident_id="INC-TEST-9901",
        plant_id="FAC-P1-L3",
        line_id="Line 3",
        severity="HIGH"
    )


# --- 1. Knowledge Graph Tests ---

def test_knowledge_graph_get_specification(kg):
    spec = kg.getSpecification("MH-8820")
    assert spec is not None
    assert spec.spec_id == "SP-8820"
    assert spec.nominal == 45.0
    assert spec.tolerance_plus == 0.020


def test_knowledge_graph_find_affected_products(kg):
    products = kg.findAffectedProducts("SP-8820")
    assert len(products) > 0
    assert any(p.sku == "EV-POW-800V" for p in products)


def test_knowledge_graph_find_approved_substitutes(kg):
    substitutes = kg.findApprovedSubstitutes("MH-8820")
    assert len(substitutes) > 0
    assert any(p.part_number == "MH-8820-PC" for p in substitutes)


# --- 2. Causal Graph Tests ---

def test_causal_graph_rank_candidate_causes(cg):
    ranked = cg.rankCandidateCauses("dimensional fault")
    assert len(ranked) >= 3
    # Verify top cause is tolerance drift per priors
    top_cause = ranked[0]
    assert top_cause.condition.condition_id == "COND-TOL-DRIFT"
    assert top_cause.weight == 0.72
    assert top_cause.rank == 1


def test_causal_graph_recalibration_loop(cg):
    old_edge = cg.get_edge("COND-TOL-DRIFT", "OUT-DIMENSIONAL-FAULT")
    initial_weight = old_edge.weight

    # Positive outcome calibration
    updated_edge = cg.recalibrate_weight("COND-TOL-DRIFT", "OUT-DIMENSIONAL-FAULT", verified=True, learning_rate=0.1)
    assert updated_edge.weight > initial_weight
    assert updated_edge.evidence_count == old_edge.evidence_count


# --- 3. Digital Twin Tests ---

def test_digital_twin_operations(dt):
    line_state = dt.get_line_state("Line 2")
    assert line_state is not None
    assert line_state.status == "OPERATIONAL"

    res_ok = dt.reserve_line_capacity("Line 2", "INC-TEST-9901", units=100, duration_hrs=2)
    assert res_ok is True


# --- 4. Agent Contract & Roster Tests ---

def test_vision_spec_agent(context):
    agent = VisionSpecAgent()
    stage_in = StageInput(stage_name="Perception", payload={"vision_data": {"measured_bore_diameter_mm": 45.08}})
    output, envelope = agent.run(context, stage_in)

    assert output.confidence > 0.90
    assert output.result["defect_detected"] is True
    assert len(output.evidence) > 0
    assert len(output.alternatives) > 0
    assert envelope.event_type == "AgentCompleted"
    assert envelope.correlation_id == context.incident_id


def test_causal_isolation_agent_end_to_end(context, kg, cg):
    agent = CausalIsolationAgent(causal_graph=cg, knowledge_graph=kg)
    stage_in = StageInput(stage_name="Reasoning", payload={"defect_type": "dimensional fault"})
    output, envelope = agent.run(context, stage_in)

    assert output.confidence >= 0.72
    assert output.result["primary_root_cause"] == "Tolerance drift on Line 2 CNC-102 (Precision Finish Spindle)"
    assert "EV-POW-800V" in output.result["affected_products"]
    assert len(output.evidence) >= 2
    assert len(output.alternatives) >= 2


def test_causal_isolation_agent_nlu_not_configured_by_default(context, kg, cg):
    # No NLU_API_KEY/NLU_URL in os.environ in the test process (see
    # knowledge/nlu_client.py's is_configured()) — proves no live call is
    # made and the insight fields degrade honestly rather than fabricating.
    agent = CausalIsolationAgent(causal_graph=cg, knowledge_graph=kg)
    stage_in = StageInput(stage_name="Reasoning", payload={"defect_type": "dimensional fault"})
    output, _ = agent.run(context, stage_in)

    assert output.result["nlu_status"] == "not_configured"
    assert output.result["nlu_sentiment"] is None
    assert output.result["nlu_keywords"] == []
    assert output.result["nlu_categories"] == []


def test_causal_isolation_agent_nlu_enriches_result_when_live(context, kg, cg, monkeypatch):
    monkeypatch.setattr(
        nlu_client,
        "analyze_text",
        lambda text, features=None: {
            "status": "live",
            "sentiment": {"document": {"score": -0.6, "label": "negative"}},
            "keywords": [{"text": "spindle vibration", "relevance": 0.9}],
            "categories": [{"label": "/industrial/manufacturing", "score": 0.8}],
        },
    )

    agent = CausalIsolationAgent(causal_graph=cg, knowledge_graph=kg)
    stage_in = StageInput(stage_name="Reasoning", payload={"defect_type": "dimensional fault"})
    output, _ = agent.run(context, stage_in)

    assert output.result["nlu_status"] == "live"
    assert output.result["nlu_sentiment"] == {"score": -0.6, "label": "negative"}
    assert output.result["nlu_keywords"] == ["spindle vibration"]
    assert output.result["nlu_categories"] == ["/industrial/manufacturing"]


def test_cad_spec_agent(context, kg):
    agent = CADSpecAgent(knowledge_graph=kg)
    stage_in = StageInput(stage_name="Reasoning", payload={"part_number": "MH-8820", "measured_value": 45.08})
    output, envelope = agent.run(context, stage_in)

    assert output.result["is_violation"] is True
    assert output.result["violation_direction"] == "UPPER"


def test_substitution_agent(context, kg):
    agent = SubstitutionAgent(knowledge_graph=kg)
    stage_in = StageInput(stage_name="CandidateGeneration", payload={"part_number": "MH-8820"})
    output, envelope = agent.run(context, stage_in)

    assert output.result["has_approved_substitute"] is True
    assert output.result["top_candidate"]["target_part_number"] == "MH-8820-PC"


def test_parameter_adjustment_agent(context, dt):
    agent = ParameterAdjustmentAgent(digital_twin=dt)
    stage_in = StageInput(stage_name="CandidateGeneration", payload={"deviation_mm": 0.08})
    output, envelope = agent.run(context, stage_in)

    assert output.result["parameter_to_adjust"] == "tool_offset_z_mm"
    assert output.result["recommended_compensation"] == -0.08


def test_impact_simulation_agent(context):
    agent = ImpactSimulationAgent()
    stage_in = StageInput(stage_name="Evaluation", payload={})
    output, envelope = agent.run(context, stage_in)

    assert output.result["top_recommendation"]["option_id"] == "OPT-1-PARAMETER-ADJUST"


def test_rerouting_agent(context, dt):
    agent = ReroutingAgent(digital_twin=dt)
    stage_in = StageInput(stage_name="Execution", payload={"selected_option": "OPT-1-PARAMETER-ADJUST"})
    output, envelope = agent.run(context, stage_in)

    assert output.result["capacity_reserved"] is True


def test_feedback_calibration_agent(context, cg):
    agent = FeedbackCalibrationAgent(causal_graph=cg)
    stage_in = StageInput(stage_name="Learning", payload={"condition_id": "COND-TOL-DRIFT", "outcome_id": "OUT-DIMENSIONAL-FAULT", "outcome_verified": True})
    output, envelope = agent.run(context, stage_in)

    assert output.result["recalibrated_weight"] > output.result["previous_weight"]
    assert envelope.event_type == "AgentCompleted"
