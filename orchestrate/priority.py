"""
Priority score — docs/005-decision-orchestrator.md: "when two incidents
compete for the same L3 reservation, the orchestrator computes a priority
score." Weights are an MVP starting point, not a tuned production model —
flagged as such below and in orchestrate/README.md.

All inputs are 0.0-1.0 except line_down_cost_per_hour_usd, which is
normalized against a reference ceiling so one runaway cost figure can't
silently dominate the score.
"""

from dataclasses import dataclass

_REFERENCE_MAX_COST_PER_HOUR_USD = 50_000.0

# MVP weights — safety dominates by design; the rest are roughly even.
# Revisit once real incident data exists to calibrate against (same open
# question as docs/005's priority score design).
_WEIGHTS = {
    "safety_impact": 0.40,
    "customer_impact": 0.15,
    "line_down_cost": 0.15,
    "production_priority": 0.15,
    "systemic": 0.15,
}


@dataclass
class PriorityInputs:
    safety_impact: float  # 0.0-1.0
    customer_impact: float  # 0.0-1.0
    line_down_cost_per_hour_usd: float
    production_priority: float  # 0.0-1.0
    is_systemic: bool  # affects a product line vs. an isolated unit


def compute_priority_score(inputs: PriorityInputs) -> float:
    normalized_cost = min(
        inputs.line_down_cost_per_hour_usd / _REFERENCE_MAX_COST_PER_HOUR_USD, 1.0
    )
    score = (
        _WEIGHTS["safety_impact"] * inputs.safety_impact
        + _WEIGHTS["customer_impact"] * inputs.customer_impact
        + _WEIGHTS["line_down_cost"] * normalized_cost
        + _WEIGHTS["production_priority"] * inputs.production_priority
        + _WEIGHTS["systemic"] * (1.0 if inputs.is_systemic else 0.0)
    )
    return round(score, 4)
