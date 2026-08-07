"""
Stand-in for the CandidateGeneration/Reserving stages this slice
intentionally excludes (see COMPARISON.md's scope section). Both
graph.py and baseline_slice.py import these same constants so a
governance-tier divergence between the two engines can only come from
orchestration mechanics, never from silently different stand-in numbers.

Values are the real OPT-1-PARAMETER-ADJUST figures
agents/impact_simulation_agent.py computes for part_number="MH-8820"
(_PARAMETER_ADJUSTMENT_NARRATIVE) — not invented, reused as constants
since ImpactSimulationAgent itself is out of slice scope. Capability
matches what tests/test_orchestrate.py::test_orchestrator_resolves_with_tier1_approval
already asserts for this exact scenario.
"""

from contracts import Capability

SLICE_CAPABILITY: Capability = Capability.SCHEDULE_MAINTENANCE
SLICE_ESTIMATED_COST_USD: float = 350.0

# The canonical demo scenario (scripts/run_orchestrator_demo.py,
# tests/test_orchestrate.py) — used consistently by both engines so
# results are directly comparable.
SCENARIO = {
    "plant_id": "FAC-P04-L2",
    "line_id": "Line 2",
    "part_number": "MH-8820",
    "vision_data": {"measured_bore_diameter_mm": 45.085},
}
