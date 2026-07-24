"""
Self-Learning Engine & Autonomy Optimization API (backend/app/routers/learning.py).
Exposes Phase 4B's learning/autonomy modules over Decision Memory's historical
precedent store — deliberately seed-backed, like memory.py's index, since this
learns from accumulated history rather than the current process's live incidents
(see executive.py's `_records()` for the contrasting live-session pattern).
"""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agents import CausalIsolationAgent
from agents.sdk import IncidentContext, StageInput, StageOutput
from executive import AutonomyPolicyOptimizer, PolicyPromotionCandidate
from knowledge import LearningEngine, LearningReplaySummary

from ..auth import require_service_auth
from .memory import get_memory_index

router = APIRouter(prefix="/learning", tags=["Self-Learning Engine"], dependencies=[Depends(require_service_auth)])


@router.get("/recalibration", response_model=LearningReplaySummary)
async def replay_causal_recalibration(learning_rate: float = 0.08):
    """Replays Decision Memory's historical outcomes to recalibrate CausalGraph edge weights."""
    engine = LearningEngine()
    return engine.replay_audit_trail(learning_rate=learning_rate)


@router.get("/promotion-candidates", response_model=List[PolicyPromotionCandidate])
async def get_promotion_candidates():
    """Evaluates historical decision clusters for Tier 0 autonomy promotion eligibility."""
    optimizer = AutonomyPolicyOptimizer()
    return optimizer.evaluate_promotion_candidates()


class MemoryRagDemoRequest(BaseModel):
    defect_type: str = "dimensional fault"
    plant_id: str = "FAC-P1-L3"
    line_id: str = "Line 3"


@router.post("/memory-rag-demo", response_model=StageOutput)
async def run_memory_rag_demo(body: MemoryRagDemoRequest):
    """
    Runs the Memory-Augmented CausalIsolationAgent against Decision Memory's
    precedent store, demonstrating confidence boosting and PRECEDENT evidence
    citations drawn from historical incidents.
    """
    agent = CausalIsolationAgent(memory_index=get_memory_index())
    context = IncidentContext(plant_id=body.plant_id, line_id=body.line_id, severity="HIGH")
    stage_in = StageInput(stage_name="Reasoning", payload={"defect_type": body.defect_type})
    output, _env = agent.run(context, stage_in)
    return output
