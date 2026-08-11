"""
P9 — regression tests for the `ados` skill's `run_capability` control flow:
the idempotency-key removal, and the new `executing`/`outcome_unknown`
handling.

Same technique `test_ados_skill_decoding.py` already established: the skill
subclasses `rlm.McpIntegration`, which only exists inside the Prime Agent
container, so the module cannot be imported here. The class body (from
`class CapabilityDenied` onward — everything that does not depend on `rlm` at
import time) is extracted and exec'd against a stub base class this file
controls, so the REAL control-flow source is what is under test, not a
reimplementation of it.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

_SKILL = (
    Path(__file__).resolve().parents[2]
    / "infrastructure" / "prime-runtime" / "ados_skill" / "src" / "ados" / "__init__.py"
)


class _StubMcpIntegration:
    """Stands in for `rlm.McpIntegration`. `call_tool` is per-test — set
    `self._script[tool_name]` to a callable(payload) -> dict, or a list of
    such callables consumed in order (for a tool called more than once, e.g.
    repeated polling)."""

    def __init__(self):
        self._script: Dict[str, Any] = {}
        self.calls: list = []

    async def call_tool(self, name: str, payload: Dict[str, Any]) -> Any:
        self.calls.append((name, payload))
        entry = self._script[name]
        fn = entry.pop(0) if isinstance(entry, list) else entry
        result = fn(payload)
        return json.dumps(result) if isinstance(result, dict) else result


def _load_ados_classes():
    """Returns (Ados, CapabilityDenied, CapabilityTimeout,
    CapabilityOutcomeUnknown) built from the REAL source, against the stub
    base class above instead of `rlm.McpIntegration`."""
    source = _SKILL.read_text()
    start = source.index("def _decoded(")
    end = source.index("\nados = Ados()")
    namespace: dict = {
        "asyncio": asyncio, "json": json, "os": os, "Any": Any, "Dict": Dict, "Optional": Optional,
        "McpIntegration": _StubMcpIntegration,
    }
    exec(compile(source[start:end], str(_SKILL), "exec"), namespace)  # noqa: S102
    return namespace["Ados"], namespace["CapabilityDenied"], namespace["CapabilityTimeout"], namespace["CapabilityOutcomeUnknown"]


Ados, CapabilityDenied, CapabilityTimeout, CapabilityOutcomeUnknown = _load_ados_classes()


def _immediate(status: str, **extra) -> dict:
    return {"status": status, "request_id": "req-1", **extra}


# --- there is no idempotency_key parameter any more ---------------------------

def test_run_capability_no_longer_accepts_an_idempotency_key():
    """The structural half of P8's finding: the parameter existed, nothing
    reachable from a real mission ever set it. P9 removes it outright rather
    than leaving a silently-ignored knob — a caller trying to pass one gets a
    real TypeError, not quiet non-behaviour."""
    ados = Ados()
    ados._script = {"request_capability": lambda payload: _immediate("executed", result={})}
    with pytest.raises(TypeError):
        asyncio.run(
            ados.run_capability("NotifyITHelpdesk", {"summary": "x"}, idempotency_key="whatever")
        )


def test_the_gateway_payload_carries_no_idempotency_key_field():
    """What is actually sent over the wire — the thing a model could
    otherwise be tempted to shape — carries no such field at all."""
    ados = Ados()
    ados._script = {"request_capability": lambda payload: _immediate("executed", result={})}
    asyncio.run(
        ados.run_capability("NotifyITHelpdesk", {"summary": "x"})
    )
    _, payload = ados.calls[0]
    assert "idempotency_key" not in payload


# --- executing is not a final answer -------------------------------------------

def test_an_immediate_executing_response_is_polled_through_not_returned():
    """If the initial `request_capability` call itself observed `executing`
    (the autonomous path never actually returns this synchronously today,
    but the skill must not assume that forever), it must not be handed back
    as though it were final."""
    ados = Ados()
    polls = iter([
        lambda payload: _immediate("executing"),
        lambda payload: _immediate("executed", result={"ok": True}),
    ])
    ados._script = {
        "request_capability": lambda payload: _immediate("executing"),
        "get_capability_request": [lambda payload: next(polls)(payload) for _ in range(2)],
    }
    result = asyncio.run(
        ados.run_capability("CreateChangeRequest", {}, poll_seconds=0)
    )
    assert result["status"] == "executed"


def test_polling_keeps_going_while_executing_and_stops_on_a_final_status():
    ados = Ados()
    sequence = iter([
        _immediate("executing"),
        _immediate("executing"),
        _immediate("executed", result={"ok": True}),
    ])
    ados._script = {
        "request_capability": lambda payload: _immediate("pending_approval"),
        "get_capability_request": lambda payload: next(sequence),
    }
    result = asyncio.run(
        ados.run_capability("CreateChangeRequest", {}, poll_seconds=0)
    )
    assert result["status"] == "executed"
    # request_capability once, then polled exactly 3 times (2x executing, 1x final)
    assert len(ados.calls) == 4


# --- outcome_unknown raises, never returns as a normal-looking result --------

def test_an_immediate_outcome_unknown_raises_not_returns():
    ados = Ados()
    ados._script = {
        "request_capability": lambda payload: _immediate(
            "outcome_unknown", reason="execution outcome unknown: stalled",
        ),
    }
    with pytest.raises(CapabilityOutcomeUnknown):
        asyncio.run(
            ados.run_capability("NotifyITHelpdesk", {"summary": "x"})
        )


def test_outcome_unknown_observed_while_polling_also_raises():
    ados = Ados()
    ados._script = {
        "request_capability": lambda payload: _immediate("pending_approval"),
        "get_capability_request": lambda payload: _immediate(
            "outcome_unknown", reason="execution outcome unknown: stalled",
        ),
    }
    with pytest.raises(CapabilityOutcomeUnknown):
        asyncio.run(
            ados.run_capability("CreateChangeRequest", {}, poll_seconds=0)
        )


def test_outcome_unknown_is_not_mistaken_for_capability_denied():
    """The two exceptions mean very different things — a denial is final and
    nothing happened; an unknown outcome might have. Conflating them would
    tell an agent "the mission wasn't granted this" for a case where ADOS
    genuinely cannot say what happened."""
    ados = Ados()
    ados._script = {"request_capability": lambda payload: _immediate("outcome_unknown", reason="r")}
    with pytest.raises(CapabilityOutcomeUnknown):
        try:
            asyncio.run(
                ados.run_capability("NotifyITHelpdesk", {"summary": "x"})
            )
        except CapabilityDenied:
            pytest.fail("outcome_unknown must not be raised as CapabilityDenied")


# --- everything that still worked before still works --------------------------

def test_denied_still_raises_capability_denied():
    ados = Ados()
    ados._script = {"request_capability": lambda payload: _immediate("denied", reason="not granted")}
    with pytest.raises(CapabilityDenied):
        asyncio.run(
            ados.run_capability("StopPayroll", {})
        )


def test_an_immediate_executed_response_returns_directly():
    ados = Ados()
    ados._script = {"request_capability": lambda payload: _immediate("executed", result={"ok": True})}
    result = asyncio.run(
        ados.run_capability("NotifyITHelpdesk", {"summary": "x"})
    )
    assert result["status"] == "executed"
    assert len(ados.calls) == 1, "an immediate result must not trigger any polling"


def test_pending_approval_still_polls_and_returns_the_final_state():
    ados = Ados()
    ados._script = {
        "request_capability": lambda payload: _immediate("pending_approval"),
        "get_capability_request": lambda payload: _immediate("executed", result={"ok": True}),
    }
    result = asyncio.run(
        ados.run_capability("CreateChangeRequest", {}, poll_seconds=0)
    )
    assert result["status"] == "executed"


def test_timeout_still_fires_if_it_stays_pending_forever():
    ados = Ados()
    ados._script = {
        "request_capability": lambda payload: _immediate("pending_approval"),
        "get_capability_request": lambda payload: _immediate("pending_approval"),
    }
    with pytest.raises(CapabilityTimeout):
        asyncio.run(
            ados.run_capability("CreateChangeRequest", {}, poll_seconds=0, timeout_seconds=0.05)
        )
