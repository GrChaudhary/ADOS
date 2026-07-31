"""
Substitution Agent implementation (Candidate Generation Stage).
Queries Knowledge Graph for approved part/supplier substitutes.
"""

from typing import Optional, List
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge import KnowledgeGraph
from knowledge.local_llm_client import local_llm_client


class SubstitutionAgent(BaseAgent):
    """Proposes compliant alternative parts or suppliers using Knowledge Graph substitution rules."""

    def __init__(self, knowledge_graph: Optional[KnowledgeGraph] = None):
        super().__init__(agent_id="substitution-agent", stage_name="CandidateGeneration")
        self.knowledge_graph = knowledge_graph or KnowledgeGraph()

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        source_part_number = stage_input.payload.get("part_number", "MH-8820")

        # Query Knowledge Graph for approved substitutes
        substitute_parts = self.knowledge_graph.findApprovedSubstitutes(source_part_number)
        rules = self.knowledge_graph.list_substitutions_for_part(source_part_number)

        candidate_substitutions = []
        for part in substitute_parts:
            # find rule details
            matched_rule = next((r for r in rules if r.target_part_number == part.part_number), None)
            candidate_substitutions.append({
                "target_part_number": part.part_number,
                "name": part.name,
                "in_stock_quantity": part.in_stock_quantity,
                "unit_cost_usd": part.unit_cost_usd,
                "cost_delta_usd": matched_rule.cost_delta_usd if matched_rule else 0.0,
                "quality_risk_score": matched_rule.quality_risk_score if matched_rule else 0.05,
                "approval_status": matched_rule.approval_status if matched_rule else "PRE_APPROVED"
            })

        # Deterministic default: first approved candidate from the
        # knowledge-graph query above. The LLM judgment below can only
        # override this with a pick that's actually in candidate_substitutions
        # — an unparseable or hallucinated part number never gets trusted,
        # since this choice can drive a real inventory reservation or
        # purchase order (orchestrate/orchestrator.py's _capability_for_option).
        top_pick = candidate_substitutions[0] if candidate_substitutions else None

        llm_result = local_llm_client.generate_substitution_reasoning(
            source_part_number=source_part_number,
            candidates=candidate_substitutions,
        )
        if llm_result.get("status") == "live_llm_generated" and llm_result.get("pick"):
            matched = next(
                (c for c in candidate_substitutions if c["target_part_number"] == llm_result["pick"]),
                None,
            )
            if matched:
                top_pick = matched

        result = {
            "source_part_number": source_part_number,
            "has_approved_substitute": len(candidate_substitutions) > 0,
            "top_candidate": top_pick,
            "candidate_substitutions": candidate_substitutions,
            "llm_status": llm_result.get("status"),
            "llm_justification": llm_result.get("justification"),
            "model_used": llm_result.get("model_used"),
        }

        evidence = []
        if top_pick:
            evidence.append(EvidenceItem(
                source_type="KNOWLEDGE_GRAPH",
                reference_id=f"SUB-RULE-{top_pick['target_part_number']}",
                description=f"Approved substitute {top_pick['target_part_number']} ({top_pick['name']}) with stock {top_pick['in_stock_quantity']} units",
                data=top_pick
            ))

        alternatives = []
        for sub in candidate_substitutions:
            if sub is top_pick:
                continue
            alternatives.append(AlternativeOption(
                option_id=f"SUB-ALT-{sub['target_part_number']}",
                description=f"Substitute with {sub['target_part_number']}",
                status="FEASIBLE",
                reason="Secondary option with higher unit cost or lower available inventory"
            ))

        return StageOutput(
            result=result,
            confidence=0.91 if candidate_substitutions else 0.40,
            evidence=evidence,
            alternatives=alternatives
        )
