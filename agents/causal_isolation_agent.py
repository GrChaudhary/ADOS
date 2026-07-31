"""
Causal Isolation Agent implementation (Reasoning Stage).
Performs root-cause analysis by querying the Causal Graph and Enterprise Knowledge Graph.
"""

from typing import Dict, Any, List, Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption, DecisionMemoryRAG
from knowledge import CausalGraph, KnowledgeGraph, DecisionMemoryIndex
from knowledge.local_llm_client import local_llm_client
from knowledge.nlu_client import nlu_client


class CausalIsolationAgent(BaseAgent):
    """
    Queries Causal Graph for ranked root causes and cross-references Knowledge Graph,
    IBM watsonx.ai Granite LLM reasoning, and Decision Memory RAG precedents.
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
        part_number = stage_input.payload.get("part_number") or context.part_number or "MH-8820"

        # Query 1: Causal Graph root cause ranking, scoped to this incident's
        # plant/line - conditions are tagged with the line they actually
        # occur on (knowledge/causal_graph.py), so a Line 1 rotor-shaft
        # incident surfaces Line 1 causes instead of Line 2's CNC-102
        # tolerance-drift narrative regardless of which line triggered it.
        ranked_causes = self.causal_graph.rankCandidateCauses(defect_type, evidence=telemetry, plant_id=context.plant_id)

        # Query 2: Knowledge Graph for affected products & specifications
        spec = self.knowledge_graph.getSpecification(part_number=part_number)
        affected_products = self.knowledge_graph.findAffectedProducts(defect_spec=spec.spec_id if spec else part_number)

        primary_cause = ranked_causes[0] if ranked_causes else None

        # Local LLM (Ollama) root-cause explanation. status is surfaced
        # as-is to result["llm_status"] below — the frontend gates its
        # "LIVE" badge on that, not on presence of text, so a fallback
        # never gets shown as if it were live generation.
        llm_reasoning = local_llm_client.generate_root_cause_explanation(
            defect_type=defect_type,
            primary_cause=primary_cause.condition.name if primary_cause else "Unknown",
            confidence=primary_cause.weight if primary_cause else 0.0,
            evidence_paths=primary_cause.evidence_path if primary_cause else [],
            part_number=part_number,
        )
        if llm_reasoning.get("status") != "live_llm_generated":
            # Honest, clearly-labeled rule-based synthesis - never claims
            # to be model output when no model actually ran.
            llm_reasoning = {
                "status": llm_reasoning.get("status", "not_configured"),
                "model_used": "Rule-based synthesis (no live LLM configured)",
                "explanation": (
                    f"{primary_cause.condition.name if primary_cause else 'Unknown cause'} identified as the "
                    f"primary root cause (confidence {(primary_cause.weight if primary_cause else 0.0) * 100:.1f}%) "
                    f"for defect '{defect_type}'."
                ),
            }

        # IBM Watson NLU pass over the reasoning explanation — keyword/
        # sentiment/category signal on top of the LLM text. Never
        # fabricated: nlu_status reflects exactly what nlu_client returned
        # (not_configured/auth_failed/error/live), and the insight fields
        # stay empty rather than guessed at when it isn't "live".
        explanation_text = llm_reasoning.get("explanation") or ""
        nlu_result = nlu_client.analyze_text(explanation_text) if explanation_text else {"status": "not_configured"}
        nlu_live = nlu_result.get("status") == "live"

        result = {
            "defect_type": defect_type,
            "primary_root_cause": primary_cause.condition.name if primary_cause else "Unknown",
            "primary_condition_id": primary_cause.condition.condition_id if primary_cause else None,
            "root_cause_confidence": primary_cause.weight if primary_cause else 0.0,
            "llm_status": llm_reasoning.get("status"),
            "llm_explanation": llm_reasoning.get("explanation"),
            "model_used": llm_reasoning.get("model_used"),
            "nlu_status": nlu_result.get("status"),
            "nlu_sentiment": nlu_result.get("sentiment", {}).get("document") if nlu_live else None,
            "nlu_keywords": [kw["text"] for kw in nlu_result.get("keywords", [])[:5]] if nlu_live else [],
            "nlu_categories": [c["label"] for c in nlu_result.get("categories", [])[:3]] if nlu_live else [],
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
