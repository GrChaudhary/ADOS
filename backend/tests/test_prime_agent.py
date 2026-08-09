"""
Tests for the RunPrimeRLMAgent capability and its real connector.

This file used to test `PrimeAgentClient.execute_rlm_task()`, which returned a
hardcoded "kernel trace" — including the lines "Auto-refined system prompt &
tool specs" and "Finalized self-improving synthesis" — for an agent that never
ran. Nothing in the codebase called it except that test, so the test was the
only thing keeping it alive. It is deleted; `PrimeRuntimeConnector` is the only
implementation now.

What is tested here is the decision the connector makes, not container
plumbing: which outcomes count as success, and what it refuses outright.
"""

import pytest
from contracts import CallStatus, Capability, CapabilityCall, GovernanceInfo, PolicyTier
from integrations.connectors.prime_runtime import (
    RUNTIME_REQUESTER_PREFIX,
    PrimeRuntimeConnector,
    response_for,
)
from integrations.hub import default_hub
from orchestrate.governance import CAPABILITY_RISK_CLASS, assign_policy_tier
from orchestrate.runtime.base import SessionOutcome, SessionState

from backend.app.routers.agents_registry import BUILTIN_AGENTS, BUILTIN_IDS


def _call(requested_by="moa", **input_) -> CapabilityCall:
    return CapabilityCall(
        capability=Capability.RUN_PRIME_RLM_AGENT,
        input=input_,
        requested_by=requested_by,
        incident_id="INC-TEST-1",
        governance=GovernanceInfo(policy_tier=PolicyTier.APPROVAL_REQUIRED),
    )


def _outcome(**kw) -> SessionOutcome:
    base = dict(
        state=SessionState.COMPLETED,
        final_answer="The root cause is connection pool exhaustion.",
        tool_execution_count=3,
        tool_success_count=3,
        tool_error_count=0,
    )
    base.update(kw)
    return SessionOutcome(**base)


# --- governance contract (unchanged behaviour, still pinned) -----------------

def test_prime_agent_capability_contracts():
    assert Capability.RUN_PRIME_RLM_AGENT == "RunPrimeRLMAgent"
    assert CAPABILITY_RISK_CLASS[Capability.RUN_PRIME_RLM_AGENT] == "medium"
    assert assign_policy_tier(
        Capability.RUN_PRIME_RLM_AGENT, confidence=0.95, estimated_cost_usd=1200.0
    ) == PolicyTier.AUTONOMOUS
    # 30k is above the low-exposure ceiling (25k) but below high exposure
    # (250k), so it needs a human but not an executive.
    assert assign_policy_tier(
        Capability.RUN_PRIME_RLM_AGENT, confidence=0.85, estimated_cost_usd=30000.0
    ) == PolicyTier.APPROVAL_REQUIRED


def test_prime_rlm_agent_is_registered():
    assert "prime-rlm-agent" in BUILTIN_IDS
    entry = next(a for a in BUILTIN_AGENTS if a.id == "prime-rlm-agent")
    assert entry.isBuiltIn


def test_the_registry_no_longer_advertises_capabilities_that_do_not_exist():
    """The entry claimed "self-improving", "harness prompt/tool auto-refinement"
    and "auto-fix bugs". None of those exist, and a description is where a
    product claim actually reaches a user."""
    entry = next(a for a in BUILTIN_AGENTS if a.id == "prime-rlm-agent")
    blurb = f"{entry.description} {entry.instructions} {entry.model}".lower()
    for claim in ("self-improving", "auto-refine", "auto-fix", "self-learning", "continual learning"):
        assert claim not in blurb, f"registry still advertises {claim!r}"


# --- connector routing -------------------------------------------------------

def test_console_does_not_win_run_prime_rlm_agent():
    """Before this connector existed, RunPrimeRLMAgent had none, so Console —
    which declares set(Capability) — returned "[console] simulated
    RunPrimeRLMAgent" and the audit row looked healthy."""
    candidates = [c.name for c in default_hub().registry.connectors_for(Capability.RUN_PRIME_RLM_AGENT)]
    assert "prime-runtime" in candidates
    assert candidates.index("prime-runtime") < candidates.index("console")


# --- what the connector refuses ---------------------------------------------

async def test_a_runtime_cannot_start_another_runtime():
    """Subagents are not a supported capability, and arriving at them by
    accident through a capability grant would be the worst way to get them.
    The gateway stamps runtime-originated calls, so the connector can tell."""
    connector = PrimeRuntimeConnector()
    response = await connector.execute(
        _call(requested_by=f"{RUNTIME_REQUESTER_PREFIX}mission:abc", prompt="do a thing")
    )
    assert response.status is CallStatus.FAILED
    assert "may not start another Prime Agent runtime" in (response.error or "")


async def test_a_call_without_a_prompt_is_rejected_before_starting_a_container():
    connector = PrimeRuntimeConnector()
    response = await connector.execute(_call(domain="it"))
    assert response.status is CallStatus.FAILED
    assert "requires a 'prompt'" in (response.error or "")


# --- what counts as success --------------------------------------------------

def test_a_real_run_succeeds_and_returns_the_answer_as_data():
    r = response_for(_call(), _outcome(), connector="prime-runtime", session_id="s1")
    assert r.status is CallStatus.SUCCEEDED
    assert r.output["tool_successes"] == 3
    assert r.output["answer"].startswith("The root cause")


def test_every_tool_call_failing_is_not_success_however_fluent_the_answer():
    """The failure this whole integration was built around: a runtime that
    could not execute a single statement still produced a confident report."""
    r = response_for(
        _call(),
        _outcome(tool_execution_count=18, tool_success_count=0, tool_error_count=18,
                 final_answer="Root cause is disk-space exhaustion on the database server."),
        connector="prime-runtime", session_id="s1",
    )
    assert r.status is CallStatus.FAILED
    assert r.output["tool_errors"] == 18


def test_a_runtime_that_did_nothing_is_not_success():
    r = response_for(
        _call(), _outcome(tool_execution_count=0, tool_success_count=0),
        connector="prime-runtime", session_id="s1",
    )
    assert r.status is CallStatus.FAILED


@pytest.mark.parametrize("state", [SessionState.FAILED, SessionState.CANCELLED])
def test_a_non_completed_session_is_never_success(state):
    r = response_for(
        _call(), _outcome(state=state, failure_reason="runtime exceeded wall clock"),
        connector="prime-runtime", session_id="s1",
    )
    assert r.status is CallStatus.FAILED
    assert "wall clock" in (r.error or "")


def test_the_answer_never_decides_the_outcome():
    """Identical observed effects must produce an identical status regardless of
    what the agent wrote."""
    a = response_for(_call(), _outcome(final_answer="Solved it perfectly."),
                     connector="prime-runtime", session_id="s1")
    b = response_for(_call(), _outcome(final_answer="I achieved nothing at all."),
                     connector="prime-runtime", session_id="s1")
    assert a.status is b.status is CallStatus.SUCCEEDED


def test_a_failed_response_still_reports_what_was_observed():
    """An operator needs the counts to tell "the model was bad" from "the
    environment was broken"."""
    r = response_for(
        _call(), _outcome(tool_execution_count=5, tool_success_count=0, tool_error_count=5),
        connector="prime-runtime", session_id="s9",
    )
    assert r.output["runtime_session_id"] == "s9"
    assert r.output["tool_executions"] == 5
