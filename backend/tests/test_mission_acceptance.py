"""
Tests for the invariant that agent narrative is never authoritative evidence.

Each test here corresponds to a way ADOS could be talked into believing work
happened when it did not. The first one is not hypothetical: it is a replay of
an observed run in which a runtime with a completely broken kernel produced a
detailed root-cause report blaming disk-space exhaustion on a database server
that appears nowhere in the incident it was assigned.
"""

import inspect

import pytest

from orchestrate.runtime.acceptance import evaluate_mission
from orchestrate.runtime.base import SessionOutcome, SessionState

FABRICATED_REPORT = """## Root Cause Analysis

The checkout-api outage was caused by disk-space exhaustion on the primary
database server. /var/lib/mysql reached 100% capacity, causing the database to
reject writes with "No space left on device"...
"""


def _outcome(**kw) -> SessionOutcome:
    base = dict(
        state=SessionState.COMPLETED,
        final_answer=FABRICATED_REPORT,
        tool_execution_count=0,
        tool_success_count=0,
        tool_error_count=0,
    )
    base.update(kw)
    return SessionOutcome(**base)


def test_a_fluent_report_from_a_broken_runtime_is_rejected():
    """The observed failure, replayed. 18 tool executions, 18 errors, a
    confident report, and ADOS must not accept it."""
    verdict = evaluate_mission(
        outcome=_outcome(tool_execution_count=18, tool_error_count=18),
        executed_capabilities=[],
        required_capabilities=["FetchIncidentEvidence"],
    )
    assert not verdict.succeeded
    assert any("could not act" in r for r in verdict.reasons)
    assert any("FetchIncidentEvidence" in r for r in verdict.reasons)


def test_a_runtime_that_reasoned_beautifully_and_called_nothing_is_rejected():
    """Working tools are not enough. If the mission required governed work and
    ADOS executed none, the mission is not complete however good the prose."""
    verdict = evaluate_mission(
        outcome=_outcome(tool_execution_count=6, tool_success_count=6),
        executed_capabilities=[],
        required_capabilities=["FetchIncidentEvidence"],
    )
    assert not verdict.succeeded
    assert any("never executed by ADOS" in r for r in verdict.reasons)


def test_tool_attempts_are_not_tool_successes():
    """An earlier version of this logic counted attempts, and scored a run of 7
    executions that ALL returned isError=true as a completed mission."""
    attempted_only = evaluate_mission(
        outcome=_outcome(tool_execution_count=7, tool_error_count=7),
        executed_capabilities=["FetchIncidentEvidence"],
        required_capabilities=["FetchIncidentEvidence"],
    )
    assert not attempted_only.succeeded

    actually_worked = evaluate_mission(
        outcome=_outcome(tool_execution_count=7, tool_success_count=7),
        executed_capabilities=["FetchIncidentEvidence"],
        required_capabilities=["FetchIncidentEvidence"],
    )
    assert actually_worked.succeeded


def test_a_clean_exit_does_not_rescue_a_mission_that_did_nothing():
    """SessionState.COMPLETED is set by the adapter, which is ADOS code — but
    it still describes how the process ENDED, not what it achieved."""
    verdict = evaluate_mission(
        outcome=_outcome(state=SessionState.COMPLETED),
        executed_capabilities=[],
        required_capabilities=[],
    )
    assert not verdict.succeeded
    assert any("did nothing" in r for r in verdict.reasons)


def test_the_narrative_cannot_influence_the_verdict():
    """The strongest form of the invariant: identical observed effects must
    produce an identical verdict no matter what the agent wrote — a confession
    of failure and a triumphant report are equally irrelevant."""
    effects = dict(
        executed_capabilities=["FetchIncidentEvidence", "NotifyITHelpdesk"],
        required_capabilities=["FetchIncidentEvidence", "NotifyITHelpdesk"],
    )
    triumphant = evaluate_mission(
        outcome=_outcome(tool_execution_count=4, tool_success_count=4,
                         final_answer="Root cause identified with high confidence."),
        **effects,
    )
    despairing = evaluate_mission(
        outcome=_outcome(tool_execution_count=4, tool_success_count=4,
                         final_answer="I was unable to determine anything."),
        **effects,
    )
    assert triumphant == despairing
    assert triumphant.succeeded


def test_evaluate_mission_cannot_see_the_agents_text_at_all():
    """Structural, not behavioural. If someone later adds a `report=` or
    `final_answer=` parameter, this fails and they have to justify it in review
    rather than in a comment nobody reads."""
    params = set(inspect.signature(evaluate_mission).parameters)
    assert params == {"outcome", "executed_capabilities", "required_capabilities"}
    forbidden = {"final_answer", "report", "narrative", "summary", "confidence", "claim"}
    assert not (params & forbidden)


def test_a_complete_mission_is_accepted():
    """The invariant must not be so strict that real work is unrecognizable."""
    verdict = evaluate_mission(
        outcome=_outcome(tool_execution_count=9, tool_success_count=8, tool_error_count=1),
        executed_capabilities=["FetchIncidentEvidence", "NotifyITHelpdesk"],
        required_capabilities=["FetchIncidentEvidence", "NotifyITHelpdesk"],
    )
    assert verdict.succeeded, verdict.reasons
    assert verdict.observed["tool_successes"] == 8
    # A single tool error along the way is normal agent behaviour (a typo, a
    # missing import) and must not fail an otherwise complete mission.
    assert verdict.observed["tool_errors"] == 1


@pytest.mark.parametrize("state", [SessionState.FAILED, SessionState.CANCELLED])
def test_a_non_completed_session_is_never_accepted(state):
    verdict = evaluate_mission(
        outcome=_outcome(state=state, tool_execution_count=5, tool_success_count=5),
        executed_capabilities=["FetchIncidentEvidence"],
        required_capabilities=["FetchIncidentEvidence"],
    )
    assert not verdict.succeeded
