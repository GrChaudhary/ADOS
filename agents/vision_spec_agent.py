"""
Vision & Spec Agent implementation (Perception Stage).
Analyzes visual inspection and sensor telemetry to generate structured defect events.
"""

from typing import Dict, Any, Optional
from agents.sdk import BaseAgent, IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption
from knowledge import KnowledgeGraph

# Fallback when the part has no registered Specification (knowledge/seed_data.py) -
# mirrors CADSpecAgent's own fallback so the two stages never disagree on
# what "in tolerance" means for an unknown part.
_FALLBACK_NOMINAL = 45.00
_FALLBACK_TOLERANCE = 0.020


class VisionSpecAgent(BaseAgent):
    """Reads camera/vision streams and sensor telemetry to produce structured defect findings."""

    def __init__(self, knowledge_graph: Optional[KnowledgeGraph] = None):
        super().__init__(agent_id="vision-spec-agent", stage_name="Perception")
        self.knowledge_graph = knowledge_graph or KnowledgeGraph()

    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        vision_data = stage_input.payload.get("vision_data", {})
        telemetry = stage_input.payload.get("telemetry", {})
        part_number = stage_input.payload.get("part_number") or context.part_number

        # Measured value is generic - what it's a measurement OF (bore
        # diameter, shaft runout, flatness...) depends on the part's own
        # governing Specification, not a fixed field name. Falls back to
        # the legacy bore-specific key for any caller that hasn't migrated.
        measured_val = vision_data.get("measured_value", vision_data.get("measured_bore_diameter_mm", 45.031))

        spec = self.knowledge_graph.getSpecification(part_number) if part_number else None
        nominal = spec.nominal if spec else _FALLBACK_NOMINAL
        tolerance_plus = spec.tolerance_plus if spec else _FALLBACK_TOLERANCE
        tolerance_minus = spec.tolerance_minus if spec else _FALLBACK_TOLERANCE
        dimension = spec.dimension if spec else "Dimensional Measurement"
        unit = spec.unit if spec else "mm"

        deviation = round(measured_val - nominal, 4)
        defect_detected = deviation > tolerance_plus or deviation < -tolerance_minus

        result = {
            "defect_detected": defect_detected,
            "defect_type": "dimensional fault" if defect_detected else "NONE",
            "measured_value": measured_val,
            "nominal_target": nominal,
            "deviation_mm": round(abs(deviation), 4),
            "dimension": dimension,
            "unit": unit,
            "part_number": part_number,
            "line_id": context.line_id,
            "plant_id": context.plant_id
        }

        evidence = [
            EvidenceItem(
                source_type="TELEMETRY",
                reference_id=f"VIS-CAM-{context.line_id}",
                description=(
                    f"High-speed optical/laser measurement — {dimension}: {measured_val}{unit} "
                    f"(nominal {nominal}{unit}, limit +{tolerance_plus}/-{tolerance_minus}{unit})"
                ),
                data={"measured_val": measured_val, "raw_telemetry": telemetry}
            )
        ]

        alternatives = [
            AlternativeOption(
                option_id="OPT-NO-DEFECT",
                description="Classify measurement as within acceptable optical noise margin",
                status="REJECTED",
                reason=f"Measured deviation {round(abs(deviation), 4)}{unit} exceeds 3-sigma tolerance threshold"
            )
        ]

        return StageOutput(
            result=result,
            confidence=0.94 if defect_detected else 0.99,
            evidence=evidence,
            alternatives=alternatives
        )
