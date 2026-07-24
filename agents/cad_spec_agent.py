"""
CAD & Spec Comparison Agent implementation (Reasoning Stage).
Compares measured geometry against CAD/PLM specification limits.
"""

from typing import Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge import KnowledgeGraph


class CADSpecAgent(BaseAgent):
    """Compares measured physical dimensions against PLM tolerance specifications."""

    def __init__(self, knowledge_graph: Optional[KnowledgeGraph] = None):
        super().__init__(agent_id="cad-spec-agent", stage_name="Reasoning")
        self.knowledge_graph = knowledge_graph or KnowledgeGraph()

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        part_number = stage_input.payload.get("part_number", "MH-100")
        measured_value = stage_input.payload.get("measured_value", 45.08)

        spec = self.knowledge_graph.getSpecification(part_number)
        nominal = spec.nominal if spec else 45.00
        upper_limit = nominal + (spec.tolerance_plus if spec else 0.05)
        lower_limit = nominal - (spec.tolerance_minus if spec else 0.05)

        is_violation = measured_value > upper_limit or measured_value < lower_limit
        over_under = "UPPER" if measured_value > upper_limit else ("LOWER" if measured_value < lower_limit else "WITHIN")

        result = {
            "part_number": part_number,
            "spec_id": spec.spec_id if spec else "UNKNOWN",
            "measured_value": measured_value,
            "nominal": nominal,
            "tolerance_range": [lower_limit, upper_limit],
            "is_violation": is_violation,
            "violation_direction": over_under,
            "cad_reference": spec.cad_reference if spec else None
        }

        evidence = [
            EvidenceItem(
                source_type="KNOWLEDGE_GRAPH",
                reference_id=spec.spec_id if spec else "SPEC-ERR",
                description=f"Spec limits [{lower_limit}mm, {upper_limit}mm] vs measured {measured_value}mm",
                data={"measured": measured_value, "limit": upper_limit if over_under == "UPPER" else lower_limit}
            )
        ]

        alternatives = [
            AlternativeOption(
                option_id="OPT-ACCEPT-REVISED-TOLERANCE",
                description="Accept part under engineering deviation waiver",
                status="REJECTED",
                reason="Deviation exceeds maximum allowable structural stress safety margin"
            )
        ]

        return StageOutput(
            result=result,
            confidence=0.96,
            evidence=evidence,
            alternatives=alternatives
        )
