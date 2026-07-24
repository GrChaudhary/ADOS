"""
Causal Isolation Agent implementation (Reasoning Stage).
Performs root-cause analysis by querying the Causal Graph and Enterprise Knowledge Graph.
"""

from typing import Dict, Any, List, Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption, DecisionMemoryRAG
from knowledge import CausalGraph, KnowledgeGraph, DecisionMemoryIndex


class CausalIsolationAgent(BaseAgent):
    """
    Queries Causal Graph for ranked root causes and cross-references Knowledge Graph
    and Decision Memory RAG precedents.
    """

    def __init__(
        self,
        causal_graph: Optional[CausalGraph] = None,
        knowledge_graph: Optional[KnowledgeGraph] = None,
        memory_index: Optional[DecisionMemoryIndex] = None
    ):
        super().__init__(agent_id="causal-isolation-agent", stage_name="Reasoning")
        self.causal_graph = causal_graph or CausalGraph()
        self.knowledge_graph = knowledge_graph or KnowledgeGraph()
        self.rag = DecisionMemoryRAG(memory_index=memory_index)

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        defect_type = stage_input.payload.get("defect_type", "dimensional fault")
        telemetry = stage_input.payload.get("telemetry", {})

        # Query 1: Causal Graph root cause ranking
        ranked_causes = self.causal_graph.rankCandidateCauses(defect_type, evidence=telemetry)

        # Query 2: Knowledge Graph for affected products & specifications
        affected_products = self.knowledge_graph.findAffectedProducts(defect_spec="SP-100")
        spec = self.knowledge_graph.getSpecification(part_number="MH-100")

        primary_cause = ranked_causes[0] if ranked_causes else None

        result = {
            "defect_type": defect_type,
            "primary_root_cause": primary_cause.condition.name if primary_cause else "Unknown",
            "primary_condition_id": primary_cause.condition.condition_id if primary_cause else None,
            "root_cause_confidence": primary_cause.weight if primary_cause else 0.0,
            "ranked_causes": [
                {
                    "rank": rc.rank,
                    "condition_id": rc.condition.condition_id,
                    "name": rc.condition.name,
                    "weight": rc.weight,
                    "evidence_path": rc.evidence_path
                }
                for rc in ranked_causes
            ],
            "affected_products": [p.sku for p in affected_products],
            "governing_spec": spec.spec_id if spec else None
        }

        # Collect evidence references
        evidence: List[EvidenceItem] = []
        if primary_cause:
            evidence.append(EvidenceItem(
                source_type="CAUSAL_GRAPH",
                reference_id=primary_cause.condition.condition_id,
                description=f"Causal link weight {primary_cause.weight} for '{primary_cause.condition.name}' -> '{defect_type}'",
                data={"weight": primary_cause.weight, "evidence_paths": primary_cause.evidence_path}
            ))

        if spec:
            evidence.append(EvidenceItem(
                source_type="KNOWLEDGE_GRAPH",
                reference_id=spec.spec_id,
                description=f"Governing Spec {spec.spec_id} ({spec.dimension} nominal: {spec.nominal}{spec.unit})",
                data=spec.model_dump(by_alias=True)
            ))

        # Capture rejected root cause candidates as alternatives
        alternatives: List[AlternativeOption] = []
        if ranked_causes:
            for rc in ranked_causes[1:]:
                alternatives.append(AlternativeOption(
                    option_id=rc.condition.condition_id,
                    description=f"Candidate Cause: {rc.condition.name}",
                    status="REJECTED",
                    reason=f"Lower causal evidence weight ({rc.weight}) compared to top cause ({primary_cause.weight if primary_cause else 0})"
                ))

        # Query 3: Decision Memory RAG precedent retrieval
        prec_evidence, prec_alts, conf_boost = self.rag.retrieve_precedents(
            defect_type=defect_type,
            condition_id=primary_cause.condition.condition_id if primary_cause else None,
            plant_id=context.plant_id
        )

        evidence.extend(prec_evidence)
        alternatives.extend(prec_alts)

        top_confidence = min(1.0, round((primary_cause.weight if primary_cause else 0.50) + conf_boost, 3))

        return StageOutput(
            result=result,
            confidence=top_confidence,
            evidence=evidence,
            alternatives=alternatives
        )
