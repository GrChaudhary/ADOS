"""
Re-routing Agent implementation (Execution Stage).
Generates execution requests and L3 reservations for capacity re-routing.
"""

from typing import Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge import DigitalTwinStore

_PRODUCTION_LINES = ["Line 1", "Line 2", "Line 3"]


def _alternate_line(target_line: str) -> str:
    """Picks a real, different production line to name as the rejected
    re-route alternative (never a nonexistent line like the old hardcoded
    "Line 4")."""
    if target_line in _PRODUCTION_LINES:
        idx = _PRODUCTION_LINES.index(target_line)
        return _PRODUCTION_LINES[(idx + 1) % len(_PRODUCTION_LINES)]
    return _PRODUCTION_LINES[0]


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

        if "SUBSTITUTION" in selected_option or "SUBSTITUTE" in selected_option or "PART" in selected_option:
            execution_steps = [
                "1. Query local SAP ERP warehouse inventory for substitute part MH-8820-PC",
                f"2. Reserve 1 unit of MH-8820-PC and dispatch to assembly {target_line}",
                "3. Perform manual alignment and physical installation on machine spindle",
                f"4. Resume production on {target_line} with verified substitute parts"
            ]
        else:
            execution_steps = [
                f"1. Send CNC parameter adjustment (tool_offset_z_mm = -0.035mm) to {target_line} PLC",
                "2. Perform 5-part sample verification sweep",
                f"3. Resume full-rate production on {target_line}"
            ]

        result = {
            "selected_option": selected_option,
            "target_line_id": target_line,
            "capacity_reserved": reserved,
            "execution_steps": execution_steps
        }

        evidence = [
            EvidenceItem(
                source_type="GLOBAL_PLANNING",
                reference_id=f"RES-{context.incident_id}",
                description=f"Soft capacity reservation locked for Line {target_line} (100 units)",
                data={"line_id": target_line, "units": 100}
            )
        ]

        alt_line = _alternate_line(target_line)
        alternatives = [
            AlternativeOption(
                option_id=f"OPT-REROUTE-{alt_line.replace(' ', '-').upper()}",
                description=f"Re-route production batch to Nova Motors Plant 04 {alt_line}",
                status="REJECTED",
                reason=f"Changeover setup time on {alt_line} requires 3.5 hours"
            )
        ]

        return StageOutput(
            result=result,
            confidence=0.95,
            evidence=evidence,
            alternatives=alternatives
        )
