"""
Phase 3 Demo: Option A/B/C Recommendation Comparison.
Shows the per-incident ranked, star-rated comparison synthesized from each
incident's own recorded alternatives (see executive/recommendation_comparison.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from executive import RecommendationComparisonEngine

HERO_INCIDENT_IDS = [
    "INC-2026-0701-001",
    "INC-2026-0703-004",
    "INC-2026-0705-012",
    "INC-2026-0710-022",
    "INC-2026-0715-030",
]


def main() -> None:
    engine = RecommendationComparisonEngine()

    print("=" * 80)
    print("      ADOS Phase 3: Option A/B/C Recommendation Comparison Demo")
    print("=" * 80)

    for incident_id in HERO_INCIDENT_IDS:
        comparison = engine.compare_options(incident_id)
        print(f"\n--- Incident: {incident_id} ---")
        if comparison is None or not comparison.options:
            print("  No recorded alternatives for this incident.")
            continue

        for opt in comparison.options:
            stars = "*" * opt.star_rating + "-" * (5 - opt.star_rating)
            pick = " <= RECOMMENDED" if opt.is_recommended else ""
            print(
                f"  Option {opt.letter} [{stars}] {opt.name}\n"
                f"      Cost: ${opt.estimated_cost_usd:,.2f} | Downtime: {opt.downtime_minutes:.0f} min | "
                f"Quality Risk: {opt.quality_risk_score:.0%} | Savings vs costliest: ${opt.savings_usd:,.2f}"
                f"{pick}"
            )

    print("\n" + "=" * 80)
    print("      SUCCESS: Phase 3 Recommendation Comparison Demo Executed Cleanly!")
    print("=" * 80)


if __name__ == "__main__":
    main()
