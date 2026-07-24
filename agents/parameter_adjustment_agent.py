"""
Parameter Adjustment Agent implementation (Candidate Generation Stage).
Computes machine parameter tuning using Digital Twin telemetry.
"""

from typing import Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge import DigitalTwinStore


class ParameterAdjustmentAgent(BaseAgent):
    """Calculates CNC machine tooling and parameter compensations to correct drift."""

    def __init__(self, digital_twin: Optional[DigitalTwinStore] = None):
        super().__init__(agent_id="parameter-adjustment-agent", stage_name="CandidateGeneration")
        self.digital_twin = digital_twin or DigitalTwinStore()

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        line_id = context.line_id
        deviation_mm = stage_input.payload.get("deviation_mm", 0.08)

        line_state = self.digital_twin.get_line_state(line_id)

        # Calculate Z-axis offset compensation to bring bore back into tolerance
        recommended_z_compensation = round(-1.0 * deviation_mm, 4)
        new_z_offset = round(0.045 + recommended_z_compensation, 4)

        result = {
            "line_id": line_id,
            "parameter_to_adjust": "tool_offset_z_mm",
            "current_value": 0.045,
            "recommended_compensation": recommended_z_compensation,
            "target_value": new_z_offset,
            "unit": "mm",
            "estimated_recovery_time_min": 12
        }

        evidence = [
            EvidenceItem(
                source_type="DIGITAL_TWIN",
                reference_id=f"TWIN-LINE-{line_id}",
                description=f"Line {line_id} active parameters: current Z-offset 0.045mm, adjustment required: {recommended_z_compensation}mm",
                data=line_state.model_dump(by_alias=True) if line_state else {}
            )
        ]

        alternatives = [
            AlternativeOption(
                option_id="OPT-FULL-TOOL-REPLACEMENT",
                description="Halt line and replace physical CNC spindle assembly",
                status="REJECTED",
                reason="Downtime cost ($14,000/hr) exceeds software parameter compensation adjustment"
            )
        ]

        return StageOutput(
            result=result,
            confidence=0.88,
            evidence=evidence,
            alternatives=alternatives
        )
