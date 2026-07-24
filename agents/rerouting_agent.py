"""
Re-routing Agent implementation (Execution Stage).
Generates execution requests and L3 reservations for capacity re-routing.
"""

from typing import Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge import DigitalTwinStore


class ReroutingAgent(BaseAgent):
    """Generates execution plan for soft reservations and line re-routing."""

    def __init__(self, digital_twin: Optional[DigitalTwinStore] = None):
        super().__init__(agent_id="rerouting-agent", stage_name="Execution")
        self.digital_twin = digital_twin or DigitalTwinStore()

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        selected_option = stage_input.payload.get("selected_option", "OPT-1-PARAMETER-ADJUST")
        target_line = context.line_id

        # Make soft reservation on digital twin
        reserved = self.digital_twin.reserve_line_capacity(
            line_id=target_line,
            incident_id=context.incident_id,
            units=100,
            duration_hrs=2
        )

        result = {
            "selected_option": selected_option,
            "target_line_id": target_line,
            "capacity_reserved": reserved,
            "execution_steps": [
                "1. Send CNC parameter adjustment (tool_offset_z_mm = -0.035mm) to Line 3 PLC",
                "2. Perform 5-part sample verification sweep",
                "3. Resume full-rate production on Line 3"
            ]
        }

        evidence = [
            EvidenceItem(
                source_type="GLOBAL_PLANNING",
                reference_id=f"RES-{context.incident_id}",
                description=f"Soft capacity reservation locked for Line {target_line} (100 units)",
                data={"line_id": target_line, "units": 100}
            )
        ]

        alternatives = [
            AlternativeOption(
                option_id="OPT-REROUTE-LINE-4",
                description="Re-route production batch to Detroit Plant Line 4",
                status="REJECTED",
                reason="Changeover setup time on Line 4 requires 3.5 hours"
            )
        ]

        return StageOutput(
            result=result,
            confidence=0.95,
            evidence=evidence,
            alternatives=alternatives
        )
