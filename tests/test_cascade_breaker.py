"""
Cascade Circuit Breaker — orchestration-platform-vision.md §5.3. A run of
individually-safe auto-approved actions must still get a human's eyes on
the whole batch once it crosses the threshold, and no timeout should ever
substitute for that.
"""

import pytest

from orchestrate.cascade_breaker import CascadeBreakerOpen, CascadeCircuitBreaker, CascadeState


def test_stays_closed_below_threshold():
    breaker = CascadeCircuitBreaker(threshold=4)
    for i in range(3):
        state = breaker.record_auto_approved("NotifyOperator", f"step {i}")
    assert state is CascadeState.CLOSED


def test_opens_at_threshold():
    breaker = CascadeCircuitBreaker(threshold=4)
    for i in range(4):
        state = breaker.record_auto_approved("NotifyOperator", f"step {i}")
    assert state is CascadeState.OPEN
    assert len(breaker.review_batch()) == 4


def test_raises_once_open_instead_of_silently_executing():
    breaker = CascadeCircuitBreaker(threshold=2)
    breaker.record_auto_approved("NotifyOperator", "step 0")
    breaker.record_auto_approved("NotifyOperator", "step 1")
    with pytest.raises(CascadeBreakerOpen):
        breaker.record_auto_approved("NotifyOperator", "step 2")


def test_human_decision_resets_streak_and_closes_breaker():
    breaker = CascadeCircuitBreaker(threshold=2)
    breaker.record_auto_approved("NotifyOperator", "step 0")
    breaker.record_auto_approved("NotifyOperator", "step 1")
    assert breaker.state is CascadeState.OPEN

    breaker.record_human_decision()
    assert breaker.state is CascadeState.CLOSED
    assert breaker.review_batch() == []

    # streak counts fresh from here — doesn't silently re-open on the very
    # next single action
    state = breaker.record_auto_approved("NotifyOperator", "step 2")
    assert state is CascadeState.CLOSED


def test_no_timeout_based_recovery_only_explicit_review_clears_it():
    breaker = CascadeCircuitBreaker(threshold=1)
    breaker.record_auto_approved("NotifyOperator", "step 0")
    assert breaker.state is CascadeState.OPEN

    # nothing but clear_after_review() can close it — no clock, no retry count
    with pytest.raises(CascadeBreakerOpen):
        breaker.record_auto_approved("NotifyOperator", "step 1")

    breaker.clear_after_review()
    assert breaker.state is CascadeState.CLOSED
    assert breaker.review_batch() == []


def test_review_batch_reflects_actual_actions_in_order():
    breaker = CascadeCircuitBreaker(threshold=3)
    breaker.record_auto_approved("NotifyOperator", "revoke slack")
    breaker.record_auto_approved("UpdateMES", "reassign tickets")
    breaker.record_auto_approved("ReserveInventory", "stop final paycheck flag")

    batch = breaker.review_batch()
    assert [a.capability for a in batch] == ["NotifyOperator", "UpdateMES", "ReserveInventory"]
    assert breaker.state is CascadeState.OPEN
