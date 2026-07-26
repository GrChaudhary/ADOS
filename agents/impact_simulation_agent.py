"""
Impact Simulation Agent implementation (Evaluation Stage).
Evaluates cost, delay, and quality risk across candidate recovery options.
"""

from typing import List, Dict, Any
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption


class ImpactSimulationAgent(BaseAgent):
    """Ranks recovery options based on cost delta, production delay, and quality risk."""

    def __init__(self):
        super().__init__(agent_id="impact-simulation-agent", stage_name="Evaluation")

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        candidates = stage_input.payload.get("candidates", [])

        # Standard simulated evaluations
        evaluated_options: List[Dict[str, Any]] = [
            {
                "option_id": "OPT-1-PARAMETER-ADJUST",
                "name": "Line 2 CNC-102 Parameter Compensation",
                "estimated_cost_usd": 350.0,
                "downtime_minutes": 12,
                "quality_risk_score": 0.08,
                "overall_score": 0.92,
                "recommendation": "TOP_PICK"
            },
            {
                "option_id": "OPT-2-PART-SUBSTITUTION",
                "name": "Substitute Component Part MH-8820-PC",
                "estimated_cost_usd": 2250.0,
                "downtime_minutes": 45,
                "quality_risk_score": 0.05,
                "overall_score": 0.78,
                "recommendation": "FEASIBLE"
            }
        ]

        top_pick = evaluated_options[0]

        result = {
            "incident_id": context.incident_id,
            "top_recommendation": top_pick,
            "ranked_options": evaluated_options,
            "evaluation_criteria": ["cost_usd", "downtime_min", "quality_risk"]
        }

        evidence = [
            EvidenceItem(
                source_type="COST_AND_SUPPLY_MODEL",
                reference_id="SIM-IMPACT-001",
                description=f"Option {top_pick['option_id']} yields lowest total MTTR penalty ($350, 12 min downtime)",
                data=top_pick
            )
        ]

        alternatives = [
            AlternativeOption(
                option_id=opt["option_id"],
                description=opt["name"],
                status="FEASIBLE",
                reason=f"Higher cost (${opt['estimated_cost_usd']}) and longer downtime ({opt['downtime_minutes']} min)"
            )
            for opt in evaluated_options[1:]
        ]

        return StageOutput(
            result=result,
            confidence=0.89,
            evidence=evidence,
            alternatives=alternatives
        )
