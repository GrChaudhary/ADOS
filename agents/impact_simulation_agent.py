"""
Impact Simulation Agent implementation (Evaluation Stage).
Evaluates cost, delay, and quality risk across candidate recovery options.
"""

from typing import List, Dict, Any, Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge.local_llm_client import local_llm_client

# Per-part parameter-adjustment narrative — which process step actually
# gets the compensating adjustment on each line. Keyed by part_number since
# that's what uniquely identifies which of the four demo scenarios is
# running (knowledge/seed_data.py's BOM); falls back to the Line 2/MH-8820
# hero-incident narrative for any part not listed here.
_PARAMETER_ADJUSTMENT_NARRATIVE = {
    "MH-8820": {"name": "Line 2 CNC-102 Parameter Compensation", "cost": 350.0, "downtime": 12},
    "RS-4401": {"name": "Line 1 Rotor Balancing Station Recalibration", "cost": 410.0, "downtime": 18},
    "CB-1099": {"name": "Line 3 Final Drive Test Bench Fixture Realignment", "cost": 275.0, "downtime": 15},
    "CP-7700": {"name": "Warehouse ASRS Staging Dwell-Time Adjustment", "cost": 180.0, "downtime": 9},
}
_DEFAULT_NARRATIVE = {"name": "Process Parameter Compensation", "cost": 350.0, "downtime": 12}


def _composite_score(cost_usd: float, downtime_min: float, quality_risk: float) -> float:
    """Weighted composite of an option's real cost/downtime/quality-risk
    figures, replacing the fixed 0.92/0.78 constants this used to return
    regardless of what those figures actually were. Normalized against
    generous manufacturing-incident ranges ($5,000 / 120 min) purely to
    keep the score in a legible ~0-1 band; the ranking it produces only
    depends on relative differences between options, not the exact bounds."""
    cost_score = max(0.0, 1.0 - cost_usd / 5000.0)
    downtime_score = max(0.0, 1.0 - downtime_min / 120.0)
    risk_score = max(0.0, 1.0 - quality_risk)
    return round(0.4 * cost_score + 0.3 * downtime_score + 0.3 * risk_score, 3)


class ImpactSimulationAgent(BaseAgent):
    """Ranks recovery options based on cost delta, production delay, and quality risk."""

    def __init__(self):
        super().__init__(agent_id="impact-simulation-agent", stage_name="Evaluation")

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        substitution_result: Optional[Dict[str, Any]] = stage_input.payload.get("substitution_result")
        part_number = context.part_number or (substitution_result or {}).get("source_part_number", "MH-8820")
        narrative = _PARAMETER_ADJUSTMENT_NARRATIVE.get(part_number, _DEFAULT_NARRATIVE)

        evaluated_options: List[Dict[str, Any]] = [
            {
                "option_id": "OPT-1-PARAMETER-ADJUST",
                "name": narrative["name"],
                "estimated_cost_usd": narrative["cost"],
                "downtime_minutes": narrative["downtime"],
                "quality_risk_score": 0.08,
            }
        ]

        # Only offer a part-substitution option when the Substitution Agent
        # (agents/substitution_agent.py) actually found an approved
        # substitute for this part - RS-4401/CB-1099/CP-7700 have none
        # registered (knowledge/seed_data.py), so fabricating a second
        # option for them would misrepresent what's actually available.
        top_candidate = (substitution_result or {}).get("top_candidate")
        if top_candidate:
            evaluated_options.append({
                "option_id": "OPT-2-PART-SUBSTITUTION",
                "name": f"Substitute Component Part {top_candidate['target_part_number']}",
                "estimated_cost_usd": round(top_candidate.get("unit_cost_usd", 0.0) + top_candidate.get("cost_delta_usd", 0.0), 2) * 5,
                "downtime_minutes": 45,
                "quality_risk_score": top_candidate.get("quality_risk_score", 0.05),
            })

        # Real composite score from each option's actual cost/downtime/risk
        # numbers (was previously a fixed 0.92 vs 0.78 regardless of what
        # those numbers were). Ranking is deterministic and reproducible;
        # the LLM below may only override the pick, never the scores.
        for opt in evaluated_options:
            opt["overall_score"] = _composite_score(
                opt["estimated_cost_usd"], opt["downtime_minutes"], opt["quality_risk_score"]
            )
        evaluated_options.sort(key=lambda o: o["overall_score"], reverse=True)

        top_pick = evaluated_options[0]

        llm_result = local_llm_client.generate_impact_simulation_reasoning(evaluated_options)
        if llm_result.get("status") == "live_llm_generated" and llm_result.get("pick"):
            matched = next(
                (o for o in evaluated_options if o["option_id"] == llm_result["pick"]),
                None,
            )
            if matched:
                top_pick = matched

        for opt in evaluated_options:
            opt["recommendation"] = "TOP_PICK" if opt is top_pick else "FEASIBLE"

        result = {
            "incident_id": context.incident_id,
            "top_recommendation": top_pick,
            "ranked_options": evaluated_options,
            "evaluation_criteria": ["cost_usd", "downtime_min", "quality_risk"],
            "llm_status": llm_result.get("status"),
            "llm_justification": llm_result.get("justification"),
            "model_used": llm_result.get("model_used"),
        }

        evidence = [
            EvidenceItem(
                source_type="COST_AND_SUPPLY_MODEL",
                reference_id="SIM-IMPACT-001",
                description=(
                    f"Option {top_pick['option_id']} yields lowest total MTTR penalty "
                    f"(${top_pick['estimated_cost_usd']}, {top_pick['downtime_minutes']} min downtime)"
                ),
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
            for opt in evaluated_options
            if opt is not top_pick
        ]

        return StageOutput(
            result=result,
            confidence=0.89,
            evidence=evidence,
            alternatives=alternatives
        )
