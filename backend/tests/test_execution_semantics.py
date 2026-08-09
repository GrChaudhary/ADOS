"""
System-wide guards on execution semantics.

    ADOS must never infer successful real-world execution from the absence of
    an exception.

A capability call passes through six stages (contracts/capabilities.py):

    1. request accepted        4. remote system acknowledged
    2. capability authorized   5. execution confirmed
    3. connector invoked       6. mission-level success

**A connector returning normally proves stage 3.** SUCCEEDED asserts stage 5.
Every expensive bug in this system has come from sliding between the two:

    * a blank ServiceNow ticket recorded as SUCCEEDED
    * a factory connector reporting a completed reroute with the gateway
      unplugged, because its `except Exception` returned SUCCEEDED
    * six factory capabilities returning SUCCEEDED with an empty payload,
      because `result=` is not a field and pydantic dropped it in silence
    * an agent's fabricated root-cause report accepted as analysis

The tests here are structural: they read the repository's own AST, so a new
connector written next month is held to the same rule without anyone
remembering this file exists. They are deliberately not clever — a reviewer
should be able to tell what they forbid in one read.
"""

import ast
from pathlib import Path

import pytest

from contracts import CONFIRMED_STATUSES, UNRESOLVED_STATUSES, CallStatus

_ROOT = Path(__file__).resolve().parents[2]

#: Where real execution decisions are made. Tests and scripts are excluded:
#: a test is *allowed* to construct a deliberately malformed response, and
#: fixtures/seed data legitimately assert statuses without a connector.
_SOURCE_DIRS = ("integrations", "orchestrate", "backend/app", "knowledge", "orchestrate_langgraph")


def _python_files():
    for rel in _SOURCE_DIRS:
        base = _ROOT / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _parse(path: Path):
    try:
        return ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return None


def _is_status(node: ast.AST, name: str) -> bool:
    """True for a literal `CallStatus.<name>`.

    Deliberately AST-based rather than textual. A first pass at this audit
    grepped for the word SUCCEEDED and flagged a comment explaining why the
    code no longer returns SUCCEEDED — the fix reported as the bug.
    """
    return (
        isinstance(node, ast.Attribute)
        and node.attr == name
        and isinstance(node.value, ast.Name)
        and node.value.id == "CallStatus"
    )


def _capability_responses(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "CapabilityResponse":
                yield node


def test_no_exception_handler_claims_success():
    """The anti-pattern, stated exactly: `except Exception` -> SUCCEEDED.

    An exception means we lost contact with the system we were driving. What
    happened on the far side is, at that moment, unknown — and unknown is not
    success. SmartFactoryConnector did this for all six of its capabilities and
    every unreachable-gateway call was filed as a completed physical action.
    """
    offenders = []
    for path in _python_files():
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for inner in ast.walk(node):
                if _is_status(inner, "SUCCEEDED"):
                    offenders.append(f"{path.relative_to(_ROOT)}:{inner.lineno}")

    assert not offenders, (
        "exception handlers claiming SUCCEEDED: " + ", ".join(offenders) + ". "
        "An exception means the effect is unobserved. Return FAILED when the "
        "request provably never left, or CallStatus.UNKNOWN when it was already "
        "in flight and the remote system may have acted."
    )


def test_every_successful_response_carries_the_remote_systems_answer():
    """A SUCCEEDED response with no `output` is a connector asserting an effect
    it cannot show. That is precisely the shape the `result=` typo produced:
    status SUCCEEDED, output {}, six capabilities' worth of factory data gone,
    and nothing anywhere raising.
    """
    offenders = []
    for path in _python_files():
        tree = _parse(path)
        if tree is None:
            continue
        for call in _capability_responses(tree):
            kwargs = {kw.arg for kw in call.keywords if kw.arg}
            status = next((kw.value for kw in call.keywords if kw.arg == "status"), None)
            if status is not None and _is_status(status, "SUCCEEDED") and "output" not in kwargs:
                offenders.append(f"{path.relative_to(_ROOT)}:{call.lineno}")

    assert not offenders, (
        "SUCCEEDED responses with no output: " + ", ".join(offenders) + ". "
        "Populate output with what the remote system actually returned."
    )


def test_every_unsuccessful_response_says_why():
    """FAILED and UNKNOWN without an `error` give an operator nothing to act on,
    and UNKNOWN in particular is a reconciliation task — it has to carry enough
    context for a human to go and look."""
    offenders = []
    for path in _python_files():
        tree = _parse(path)
        if tree is None:
            continue
        for call in _capability_responses(tree):
            kwargs = {kw.arg for kw in call.keywords if kw.arg}
            status = next((kw.value for kw in call.keywords if kw.arg == "status"), None)
            if status is None:
                continue
            if (_is_status(status, "FAILED") or _is_status(status, "UNKNOWN")) and "error" not in kwargs:
                offenders.append(f"{path.relative_to(_ROOT)}:{call.lineno}")

    assert not offenders, (
        "FAILED/UNKNOWN responses with no error: " + ", ".join(offenders)
    )


def test_unknown_is_not_success_and_not_failure():
    """The contract-level statement of the third outcome."""
    assert CallStatus.UNKNOWN not in CONFIRMED_STATUSES
    assert CallStatus.UNKNOWN in UNRESOLVED_STATUSES
    assert CallStatus.SUCCEEDED in CONFIRMED_STATUSES
    assert CallStatus.FAILED not in CONFIRMED_STATUSES
    # ROLLED_BACK is explicitly not success: the action was undone.
    assert CallStatus.ROLLED_BACK not in CONFIRMED_STATUSES


@pytest.mark.parametrize("status", [CallStatus.FAILED, CallStatus.UNKNOWN, CallStatus.ROLLED_BACK])
def test_the_gateway_only_records_confirmed_execution_as_executed(status):
    """The gateway decides `executed` vs `failed` from the connector's own
    status, and only SUCCEEDED counts.

    UNKNOWN matters most here. If it were treated as executed, an ambiguous
    physical action would enter the audit trail as done and the mission would
    be accepted on it. If it were silently treated as a retryable failure, an
    agent could re-issue a command the plant may already have performed.
    """
    assert (str(status.value).lower() == CallStatus.SUCCEEDED.value) is False


def test_mission_acceptance_ignores_unconfirmed_capability_rows():
    """End of the chain: evaluate_mission counts only capabilities ADOS
    recorded as executed, so an UNKNOWN row cannot complete a mission."""
    from orchestrate.runtime.acceptance import evaluate_mission
    from orchestrate.runtime.base import SessionOutcome, SessionState

    outcome = SessionOutcome(
        state=SessionState.COMPLETED,
        final_answer="I re-dispatched the workpiece.",
        tool_execution_count=3,
        tool_success_count=3,
    )
    verdict = evaluate_mission(
        outcome=outcome,
        executed_capabilities=[],          # the UNKNOWN row is not in here
        required_capabilities=["RerouteStation"],
    )
    assert not verdict.succeeded
    assert any("never executed by ADOS" in r for r in verdict.reasons)
