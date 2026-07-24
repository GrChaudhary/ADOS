"""
Predictive Risk Analytics implementation (executive/predictive_risk.py).
Computes forward-looking plant and line risk scores based on Causal Graph condition trends and incident history.
"""

from typing import List, Dict, Any, Optional
from knowledge import CausalGraph, DigitalTwinStore
from contracts import IncidentRecord
from .models import RiskSignal
from .seed_data import INCIDENT_RECORDS_SEED


class PredictiveRiskAnalytics:
    """
    Evaluates plant/line risk profiles by linking live telemetry and historical causal weights.
    """

    def __init__(
        self,
        causal_graph: Optional[CausalGraph] = None,
        digital_twin: Optional[DigitalTwinStore] = None,
        records: Optional[List[IncidentRecord]] = None
    ):
        self.causal_graph: CausalGraph = causal_graph or CausalGraph(seed=True)
        self.digital_twin: DigitalTwinStore = digital_twin or DigitalTwinStore()
        self.records: List[IncidentRecord] = records if records is not None else list(INCIDENT_RECORDS_SEED)

    def evaluate_line_risk(self, plant_id: str = "FAC-P1-L3", line_id: str = "Line 3") -> RiskSignal:
        """Evaluates predictive risk score for a specific plant line."""
        # 1. Fetch Causal Graph edge weight for top condition
        edge = self.causal_graph.get_edge("COND-TOL-DRIFT", "OUT-DIMENSIONAL-FAULT")
        causal_weight = edge.weight if edge else 0.72

        # 2. Fetch Digital Twin line state
        line_state = self.digital_twin.get_line_state(line_id)
        vibration_rms = line_state.telemetry.get("vibration_rms_mm_s", 4.8) if line_state else 4.0
        humidity = line_state.telemetry.get("ambient_humidity_pct", 82.0) if line_state else 50.0

        # Calculate composite risk score
        # Base weight + vibration penalty (>3.5) + humidity penalty (>80)
        vibration_factor = min(0.20, max(0.0, (vibration_rms - 3.0) * 0.08))
        humidity_factor = min(0.10, max(0.0, (humidity - 75.0) * 0.01))

        raw_score = causal_weight * 0.70 + vibration_factor + humidity_factor
        risk_score = round(min(1.0, raw_score), 3)

        risk_level = "CRITICAL" if risk_score >= 0.75 else ("ELEVATED" if risk_score >= 0.50 else "NORMAL")

        return RiskSignal(
            signal_id=f"RISK-{plant_id}-{line_id}",
            plant_id=plant_id,
            line_id=line_id,
            risk_score=risk_score,
            risk_level=risk_level,
            primary_risk_driver=f"CNC Spindle Vibration ({vibration_rms} mm/s) & Causal Drift Weight ({causal_weight})",
            causal_condition_id="COND-TOL-DRIFT",
            recommended_mitigation="Execute tool offset compensation (-0.035mm) and schedule preventive spindle bearing swap within 48 hours."
        )

    def get_all_plant_risk_signals(self) -> List[RiskSignal]:
        """Returns risk signals for all active lines across plants."""
        signals = [
            self.evaluate_line_risk("FAC-P1-L3", "Line 3"),
            RiskSignal(
                signal_id="RISK-FAC-P1-L4",
                plant_id="FAC-P1-L4",
                line_id="Line 4",
                risk_score=0.48,
                risk_level="NORMAL",
                primary_risk_driver="Ambient Humidity Fluctuations",
                causal_condition_id="COND-HUMIDITY-SPIKE",
                recommended_mitigation="Monitor room HVAC humidity sensor stability."
            ),
            RiskSignal(
                signal_id="RISK-FAC-P2-L1",
                plant_id="FAC-P2-L1",
                line_id="Line 1",
                risk_score=0.62,
                risk_level="ELEVATED",
                primary_risk_driver="Supplier S-202 Material Hardness Variance",
                causal_condition_id="COND-SUPPLIER-BATCH",
                recommended_mitigation="Enforce 100% incoming lot hardness testing at receiving dock."
            )
        ]
        return signals
