"""
Causal Graph store & calibration loop implementation per docs/003-causal-graph.md.
"""

from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timezone
from .causal_models import ConditionNode, OutcomeNode, CausalEdge, CausalRankResult


class CausalGraph:
    """
    Weighted condition->outcome causal model store.
    Provides root-cause ranking query and outcome recalibration loop.
    """

    def __init__(self, seed: bool = True):
        self._conditions: Dict[str, ConditionNode] = {}
        self._outcomes: Dict[str, OutcomeNode] = {}  # key: outcome_id or defect_type
        self._edges: Dict[Tuple[str, str], CausalEdge] = {}  # key: (condition_id, outcome_id)

        if seed:
            self._load_seed_priors()

    def _load_seed_priors(self) -> None:
        """Seed priors per docs/003-causal-graph.md illustration."""
        c1 = ConditionNode(
            condition_id="COND-TOL-DRIFT",
            name="Tolerance drift on Line 3 CNC Spindle",
            condition_type="PROCESS_PARAMETER",
            description="Tooling wear causing spindle runout outside +/-0.03mm nominal",
            plant_id="FAC-P1-L3"
        )
        c2 = ConditionNode(
            condition_id="COND-SUPPLIER-BATCH",
            name="Supplier batch change (Lot #B-9021)",
            condition_type="SUPPLIER",
            description="Raw material hardness shift in recent supplier shipment",
            plant_id="FAC-P1-L3"
        )
        c3 = ConditionNode(
            condition_id="COND-HUMIDITY-SPIKE",
            name="Ambient humidity spike (>85%)",
            condition_type="ENVIRONMENT",
            description="Plant floor environmental sensor reading high humidity",
            plant_id="FAC-P1-L3"
        )

        o1 = OutcomeNode(
            outcome_id="OUT-DIMENSIONAL-FAULT",
            defect_type="dimensional fault",
            description="Part bore diameter outside specification limits"
        )

        self.add_condition(c1)
        self.add_condition(c2)
        self.add_condition(c3)
        self.add_outcome(o1)

        # Seed edges with priors
        self.add_causal_edge(CausalEdge(
            condition_id=c1.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.72,
            evidence_count=14,
            evidence_paths=["CNC Telemetry -> Spindle Vibration -> Bore Measurement Deviation"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c2.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.41,
            evidence_count=6,
            evidence_paths=["ERP Goods Receipt -> Batch Lot B-9021 -> Hardness Testing Log"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c3.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.18,
            evidence_count=2,
            evidence_paths=["PLC Environmental Sensor -> Room Humidity Log"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

    def add_condition(self, condition: ConditionNode) -> None:
        self._conditions[condition.condition_id] = condition

    def add_outcome(self, outcome: OutcomeNode) -> None:
        self._outcomes[outcome.outcome_id] = outcome
        self._outcomes[outcome.defect_type.lower()] = outcome

    def add_causal_edge(self, edge: CausalEdge) -> None:
        key = (edge.condition_id, edge.outcome_id)
        self._edges[key] = edge

    # --- Mandatory Query Surface per docs/003-causal-graph.md ---

    def rankCandidateCauses(self, defect_type: str, evidence: Optional[Dict[str, Any]] = None) -> List[CausalRankResult]:
        """
        Given an observed defect and associated telemetry evidence,
        returns a ranked list of candidate root causes with confidence weights & evidence paths.
        """
        outcome = self._outcomes.get(defect_type.lower())
        if not outcome:
            # Fallback: search by outcome_id or partial match
            for o in self._outcomes.values():
                if defect_type.lower() in o.defect_type.lower() or defect_type.lower() in o.outcome_id.lower():
                    outcome = o
                    break

        if not outcome:
            return []

        candidates: List[Tuple[ConditionNode, CausalEdge]] = []
        for (cond_id, out_id), edge in self._edges.items():
            if out_id == outcome.outcome_id:
                cond = self._conditions.get(cond_id)
                if cond:
                    candidates.append((cond, edge))

        # Adjust weights slightly if evidence matches specific condition hints
        ranked_items = []
        for cond, edge in candidates:
            adjusted_weight = edge.weight
            if evidence:
                # If telemetry explicitly references this condition's domain, boost weight
                if evidence.get("telemetry_anomaly") == "VIBRATION" and cond.condition_type == "PROCESS_PARAMETER":
                    adjusted_weight = min(1.0, adjusted_weight * 1.15)
                elif evidence.get("supplier_batch_changed") and cond.condition_type == "SUPPLIER":
                    adjusted_weight = min(1.0, adjusted_weight * 1.15)

            ranked_items.append((cond, adjusted_weight, edge.evidence_paths))

        # Sort descending by weight
        ranked_items.sort(key=lambda x: x[1], reverse=True)

        results: List[CausalRankResult] = []
        for idx, (cond, w, ev_path) in enumerate(ranked_items, start=1):
            results.append(CausalRankResult(
                condition=cond,
                weight=round(w, 4),
                evidence_path=ev_path,
                rank=idx
            ))

        return results

    # --- Calibration Hook for Feedback & Calibration Agent ---

    def recalibrate_weight(
        self,
        condition_id: str,
        outcome_id: str,
        verified: bool,
        learning_rate: float = 0.05
    ) -> Optional[CausalEdge]:
        """
        Updates edge weight based on outcome verification (Bayesian/frequency recalibration).
        """
        key = (condition_id, outcome_id)
        edge = self._edges.get(key)
        if not edge:
            return None

        edge.evidence_count += 1
        if verified:
            # Shift weight up towards 1.0
            edge.weight = round(min(1.0, edge.weight + learning_rate * (1.0 - edge.weight)), 4)
        else:
            # Shift weight down towards 0.0
            edge.weight = round(max(0.0, edge.weight - learning_rate * edge.weight), 4)

        edge.last_updated = datetime.now(timezone.utc).isoformat()
        return edge

    def get_edge(self, condition_id: str, outcome_id: str) -> Optional[CausalEdge]:
        return self._edges.get((condition_id, outcome_id))
