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
        """Seed priors per docs/003-causal-graph.md illustration.

        Nova Motors Plant 04 (Bangalore, Karnataka) demo dataset
        (documentation/02_Demo_Dataset_and_Digital_Twin.md): 8 incident
        categories, hero incident is Motor Housing (MH-8820) bore tolerance
        breach on Line 2 / CNC-102 Precision Finish Spindle (FAC-P04-L2).
        CNC-101, CNC-102, ROB-401, and CMM-02 are all Line 2 cells per the
        documented Housing Machining & Inspection topology."""
        c1 = ConditionNode(
            condition_id="COND-TOL-DRIFT",
            name="Tolerance drift on Line 2 CNC-102 (Precision Finish Spindle)",
            condition_type="PROCESS_PARAMETER",
            description="Tooling wear causing spindle runout outside +/-0.020mm bore tolerance",
            plant_id="FAC-P04-L2"
        )
        c2 = ConditionNode(
            condition_id="COND-SUPPLIER-BATCH",
            name="Supplier batch change (Titan Metals Lot #B-409)",
            condition_type="SUPPLIER",
            description="Casting porosity in recent Titan Metals Inc. Motor Housing shipment",
            plant_id="FAC-P04-L2"
        )
        c3 = ConditionNode(
            condition_id="COND-HUMIDITY-SPIKE",
            name="Ambient humidity spike (>75%)",
            condition_type="ENVIRONMENT",
            description="Plant floor environmental sensor reading high humidity causing thermal expansion",
            plant_id="FAC-P04-L2"
        )
        c4 = ConditionNode(
            condition_id="COND-TOOL-WEAR",
            name="CNC-101 tool wear beyond service interval",
            condition_type="EQUIPMENT",
            description="Carbide bore reamer (Tooling Assembly T-882) wear exceeding recommended replacement threshold",
            plant_id="FAC-P04-L2"
        )
        c5 = ConditionNode(
            condition_id="COND-CALIBRATION-DRIFT",
            name="CMM-02 calibration drift",
            condition_type="EQUIPMENT",
            description="Automated Laser Coordinate Measurement Machine calibration outside acceptable drift window",
            plant_id="FAC-P04-L2"
        )
        c6 = ConditionNode(
            condition_id="COND-MACHINE-VIBRATION",
            name="ROB-401 excess vibration",
            condition_type="EQUIPMENT",
            description="Abnormal vibration signature on the 6-Axis Robotic Transfer Arm joint actuator",
            plant_id="FAC-P04-L2"
        )
        c7 = ConditionNode(
            condition_id="COND-MATERIAL-MISMATCH",
            name="Stator core material certification mismatch",
            condition_type="SUPPLIER",
            description="Incoming electrical steel lamination lot fails material certification cross-check",
            plant_id="FAC-P04-L1"
        )
        c8 = ConditionNode(
            condition_id="COND-SHIPPING-DELAY",
            name="Inbound shipment delay",
            condition_type="SUPPLIER",
            description="Carrier-reported delay on inbound supplier shipment to Central Warehouse",
            plant_id="FAC-P04-WH"
        )
        c9 = ConditionNode(
            condition_id="COND-TESTBENCH-MISALIGN",
            name="TEST-BENCH-01 fixture misalignment (Final Drive Test Bench)",
            condition_type="EQUIPMENT",
            description="Bearing seat fixture on the final-drive test bench drifted out of registration, offsetting outer-diameter readings",
            plant_id="FAC-P04-L3"
        )
        c10 = ConditionNode(
            condition_id="COND-BEARING-LOT-VARIANCE",
            name="Ceramic bearing supplier lot variance (PrecisionCast GmbH)",
            condition_type="SUPPLIER",
            description="Incoming Si3N4 ceramic bearing lot shows outer-diameter grinding variance above historical baseline",
            plant_id="FAC-P04-L3"
        )
        c11 = ConditionNode(
            condition_id="COND-ASRS-THERMAL-WARP",
            name="ASRS-01 staging bay thermal cycling warp",
            condition_type="ENVIRONMENT",
            description="Cooling plate held in an Automated Storage & Retrieval bay near a loading-dock door shows brazed-joint warp from repeated thermal cycling",
            plant_id="FAC-P04-WH"
        )
        c12 = ConditionNode(
            condition_id="COND-OUTBOUND-HANDLING-STRESS",
            name="Outbound handling stress deformation",
            condition_type="PROCESS_PARAMETER",
            description="Pack-out crating pressure applied to stacked cooling plates exceeds the flatness-preserving load limit",
            plant_id="FAC-P04-WH"
        )

        o1 = OutcomeNode(
            outcome_id="OUT-DIMENSIONAL-FAULT",
            defect_type="dimensional fault",
            description="Part bore diameter outside specification limits"
        )
        o2 = OutcomeNode(
            outcome_id="OUT-SUPPLY-DISRUPTION",
            defect_type="supply disruption",
            description="Production input unavailable or delayed at the point of need"
        )

        for c in (c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12):
            self.add_condition(c)
        self.add_outcome(o1)
        self.add_outcome(o2)

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

        self.add_causal_edge(CausalEdge(
            condition_id=c4.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.63,
            evidence_count=9,
            evidence_paths=["CNC Tool Life Counter -> Wear Threshold Exceeded"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c5.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.34,
            evidence_count=4,
            evidence_paths=["CMM Calibration Log -> Drift Outside Window"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c6.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.29,
            evidence_count=3,
            evidence_paths=["Robot Arm Accelerometer -> Vibration Signature Anomaly"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c7.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.47,
            evidence_count=5,
            evidence_paths=["Incoming QA -> Material Certification Cross-Check Failure"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c8.condition_id,
            outcome_id=o2.outcome_id,
            weight=0.55,
            evidence_count=7,
            evidence_paths=["Carrier EDI 214 -> Delay Notification"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c9.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.68,
            evidence_count=11,
            evidence_paths=["Test Bench Fixture Encoder -> Registration Drift Log"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c10.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.39,
            evidence_count=5,
            evidence_paths=["Incoming QA -> Bearing Lot Grinding Variance Report"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c11.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.61,
            evidence_count=8,
            evidence_paths=["ASRS Bay Thermal Log -> Cycling Count Threshold Exceeded"],
            last_updated=datetime.now(timezone.utc).isoformat()
        ))

        self.add_causal_edge(CausalEdge(
            condition_id=c12.condition_id,
            outcome_id=o1.outcome_id,
            weight=0.33,
            evidence_count=4,
            evidence_paths=["Pack-Out Load Cell -> Crating Pressure Exceedance"],
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

    def rankCandidateCauses(
        self, defect_type: str, evidence: Optional[Dict[str, Any]] = None, plant_id: Optional[str] = None
    ) -> List[CausalRankResult]:
        """
        Given an observed defect and associated telemetry evidence,
        returns a ranked list of candidate root causes with confidence weights & evidence paths.

        `plant_id` scopes the result to the line the defect actually occurred
        on (each ConditionNode carries the plant/line it applies to) so a
        Line 1 rotor-shaft incident doesn't surface Line 2's CNC-102
        tolerance-drift narrative. Falls back to the full candidate set for
        that outcome when no condition is tagged for the given plant_id, so
        a still-sparse line degrades to "less specific" rather than "empty".
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

        if plant_id:
            scoped = [(cond, edge) for cond, edge in candidates if cond.plant_id == plant_id]
            if scoped:
                candidates = scoped

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
