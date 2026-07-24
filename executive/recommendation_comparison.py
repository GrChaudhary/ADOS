"""
Recommendation Comparison Engine (executive/recommendation_comparison.py).

Per-incident "Option A/B/C" comparison — Blueprints/ADOS_Demo_Product_Experience_Blueprint.md's
"Recommendation Screen" — as opposed to RecommendationEngine's cross-incident
strategic recommendations, which this module doesn't replace.

Sourced entirely from IncidentRecord.alternatives, which
orchestrate/orchestrator.py populates from the Impact Simulation Agent's
ranked_options (agents/impact_simulation_agent.py) at incident finalization.

Deliberately does not fabricate a "do nothing / wait N days" revenue-loss
option: no $/minute-of-downtime revenue assumption exists anywhere else in
this codebase, and inventing one here would be an ungrounded number. Instead,
`savings_usd` is computed relative to the most expensive recorded alternative
for the same incident — every figure traces back to something an agent
actually computed.
"""

from typing import Dict, List, Optional

from contracts import IncidentRecord
from .models import IncidentComparison, IncidentOption
from .seed_data import INCIDENT_RECORDS_SEED

_LETTERS = ["A", "B", "C", "D", "E"]


class RecommendationComparisonEngine:
    """Builds a ranked, star-rated Option A/B/C comparison for one incident."""

    def __init__(self, records: Optional[List[IncidentRecord]] = None):
        self.records: List[IncidentRecord] = records if records is not None else list(INCIDENT_RECORDS_SEED)
        self._by_id: Dict[str, IncidentRecord] = {r.incident_id: r for r in self.records}

    def compare_options(self, incident_id: str) -> Optional[IncidentComparison]:
        """Returns the Option A/B/C comparison for `incident_id`, or None if
        no incident with that ID is known. An incident with no recorded
        alternatives (e.g. still in progress, or resolved with a single
        forced option) yields an IncidentComparison with an empty options
        list rather than None."""
        record = self._by_id.get(incident_id)
        if record is None:
            return None

        alternatives = record.alternatives or []
        if not alternatives:
            return IncidentComparison(incidentId=incident_id, options=[])

        ranked = sorted(alternatives, key=lambda alt: alt.get("overall_score", 0.0), reverse=True)
        max_cost = max(alt.get("estimated_cost_usd", 0.0) for alt in ranked)

        options: List[IncidentOption] = []
        for idx, alt in enumerate(ranked):
            cost = alt.get("estimated_cost_usd", 0.0)
            score = alt.get("overall_score", 0.0)
            options.append(IncidentOption(
                letter=_LETTERS[idx] if idx < len(_LETTERS) else str(idx + 1),
                optionId=alt.get("option_id", f"OPT-{idx + 1}"),
                name=alt.get("name", "Unnamed Option"),
                estimatedCostUsd=cost,
                downtimeMinutes=alt.get("downtime_minutes", 0.0),
                qualityRiskScore=alt.get("quality_risk_score", 0.0),
                overallScore=score,
                recommendation=alt.get("recommendation", "FEASIBLE"),
                savingsUsd=round(max_cost - cost, 2),
                starRating=max(1, min(5, round(score * 5))),
                isRecommended=(idx == 0),
            ))

        return IncidentComparison(incidentId=incident_id, options=options)
