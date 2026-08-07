"""
Severity Triage Agent — extensibility experiment only (Perception stage).
Not part of either engine's default pipeline; exists so
orchestrate_langgraph/COMPARISON.md's "add one new stage" experiment has an
identical, deterministic agent to wire into both the custom engine and the
LangGraph slice, isolating the wiring-diff comparison from any difference
in the agent's own logic. See orchestrate_langgraph/extensibility_experiment/.
"""

from typing import Any, Dict

from agents.sdk import BaseAgent, EvidenceItem, IncidentContext, StageInput, StageOutput

_THRESHOLDS = (
    (0.10, "CRITICAL"),
    (0.05, "HIGH"),
    (0.02, "MEDIUM"),
)


class SeverityTriageAgent(BaseAgent):
    """Buckets a defect's deviation magnitude into a severity label."""

    def __init__(self):
        super().__init__(agent_id="severity-triage-agent", stage_name="Perception")

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        deviation_mm = stage_input.payload.get("deviation_mm", 0.0)
        severity = "LOW"
        for threshold, label in _THRESHOLDS:
            if deviation_mm >= threshold:
                severity = label
                break

        result: Dict[str, Any] = {"severity": severity, "deviation_mm": deviation_mm}
        evidence = [
            EvidenceItem(
                source_type="TELEMETRY",
                reference_id="SEVERITY-TRIAGE",
                description=f"deviation {deviation_mm}mm -> {severity}",
                data={"deviation_mm": deviation_mm},
            )
        ]
        return StageOutput(result=result, confidence=1.0, evidence=evidence, alternatives=[])
