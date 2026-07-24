"""
Unit tests for Recommendation Comparison Engine (executive/recommendation_comparison.py)
— Phase 3's per-incident Option A/B/C comparison.
"""

import pytest

from executive import RecommendationComparisonEngine


@pytest.fixture
def engine():
    return RecommendationComparisonEngine()


def test_compare_options_ranks_and_labels(engine):
    # INC-2026-0703-004: substitution (TOP_PICK) vs. waiting for resupply (FEASIBLE)
    comparison = engine.compare_options("INC-2026-0703-004")

    assert comparison is not None
    assert comparison.incident_id == "INC-2026-0703-004"
    assert len(comparison.options) == 2

    option_a, option_b = comparison.options
    assert option_a.letter == "A"
    assert option_a.is_recommended is True
    assert option_a.recommendation == "TOP_PICK"
    assert option_a.overall_score > option_b.overall_score

    assert option_b.letter == "B"
    assert option_b.is_recommended is False


def test_compare_options_savings_relative_to_costliest_alternative(engine):
    comparison = engine.compare_options("INC-2026-0703-004")
    option_a, option_b = comparison.options

    # Savings is computed vs. the most expensive recorded alternative.
    assert option_b.estimated_cost_usd >= option_a.estimated_cost_usd
    assert option_b.savings_usd == 0.0
    assert option_a.savings_usd == round(option_b.estimated_cost_usd - option_a.estimated_cost_usd, 2)
    assert option_a.savings_usd > 0


def test_compare_options_star_rating_derived_from_score(engine):
    comparison = engine.compare_options("INC-2026-0710-022")
    top = comparison.options[0]

    assert top.star_rating == max(1, min(5, round(top.overall_score * 5)))
    assert 1 <= top.star_rating <= 5


def test_compare_options_unknown_incident_returns_none(engine):
    assert engine.compare_options("INC-DOES-NOT-EXIST") is None


def test_compare_options_no_alternatives_returns_empty_list(engine):
    # Generated historical incidents (executive/incident_generator.py) don't
    # carry recorded alternatives — a legitimate "no options on record" case.
    comparison = engine.compare_options("INC-GEN-0001")

    assert comparison is not None
    assert comparison.options == []
