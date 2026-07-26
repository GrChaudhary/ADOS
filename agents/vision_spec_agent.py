"""
Vision & Spec Agent implementation (Perception Stage).
Analyzes visual inspection and sensor telemetry to generate structured defect events.
"""

from typing import Dict, Any
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption


class VisionSpecAgent(BaseAgent):
    """Reads camera/vision streams and sensor telemetry to produce structured defect findings."""

    def __init__(self):
        super().__init__(agent_id="vision-spec-agent", stage_name="Perception")

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        vision_data = stage_input.payload.get("vision_data", {})
        telemetry = stage_input.payload.get("telemetry", {})

        measured_val = vision_data.get("measured_bore_diameter_mm", 45.031)
        defect_detected = measured_val > 45.020 or measured_val < 44.980

        result = {
            "defect_detected": defect_detected,
            "defect_type": "dimensional fault" if defect_detected else "NONE",
            "measured_value": measured_val,
            "nominal_target": 45.00,
            "deviation_mm": round(abs(measured_val - 45.00), 4),
            "line_id": context.line_id,
            "plant_id": context.plant_id
        }

        evidence = [
            EvidenceItem(
                source_type="TELEMETRY",
                reference_id=f"VIS-CAM-{context.line_id}",
                description=f"High-speed optical camera measurement: {measured_val}mm (limit: +/-0.020mm)",
                data={"measured_val": measured_val, "raw_telemetry": telemetry}
            )
        ]

        alternatives = [
            AlternativeOption(
                option_id="OPT-NO-DEFECT",
                description="Classify measurement as within acceptable optical noise margin",
                status="REJECTED",
                reason=f"Measured deviation {round(abs(measured_val - 45.00), 4)}mm exceeds 3-sigma tolerance threshold"
            )
        ]

        return StageOutput(
            result=result,
            confidence=0.94 if defect_detected else 0.99,
            evidence=evidence,
            alternatives=alternatives
        )
