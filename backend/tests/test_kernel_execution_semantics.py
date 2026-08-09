"""
Did the kernel actually run the code? — regression tests for a run that said
`tools=4 ok=4 err=0` while three of the four cells raised SyntaxError.

THE DEFECT
----------
`tool_execution_end.isError` does not mean "the execution failed". Prime
Agent's core hardcodes it:

    // executePreparedToolCall
    return { result, isError: false };
    ...
    } catch (error) { ... isError: true }

It answers "did the tool function throw?". The ipython tool computes the real
verdict (`isError: r.status === "error" || r.status === "aborted"`), returns it,
and the core discards it. The kernel's answer survives only in
`result.details.status`.

WHY IT MATTERS MORE THAN A COUNTER
----------------------------------
`SessionOutcome.did_real_work` is `tool_success_count > 0`, and it is the check
that catches a runtime which could not act and wrote a confident report anyway.
Scoring dispatches as successes made that check blind to the exact class of
failure it exists to catch. `test_the_old_isError_only_rule_would_pass_this`
below is the negative control: it reproduces the old rule and demonstrates that
it scores a SyntaxError run as fully successful.

The event fixtures here are real shapes captured from RPC runs, not invented.
"""

from dataclasses import replace

import pytest

from orchestrate.runtime.acceptance import evaluate_mission
from orchestrate.runtime.base import AgentSessionSpec, SessionOutcome, SessionState
from orchestrate.runtime.prime import PrimeAgentRuntime, classify_tool_execution


def _end(*, is_error=False, status=None, ename=None, result_is_error=None, tool="ipython"):
    """A tool_execution_end event in Prime Agent's real shape."""
    details = {}
    if status is not None:
        details["status"] = status
    if ename is not None:
        details["errorEname"] = ename
    result = {"content": [{"type": "text", "text": "…"}], "details": details}
    if result_is_error is not None:
        result["isError"] = result_is_error
    return {
        "type": "tool_execution_end",
        "toolName": tool,
        "toolCallId": "call_x",
        "result": result,
        "isError": is_error,
    }


# --- the four required cases -------------------------------------------------

def test_isError_false_and_status_ok_is_a_success():
    """Captured from diag2.jsonl: a cell that really ran."""
    assert classify_tool_execution(_end(is_error=False, status="ok")) == "ok"


def test_isError_false_and_status_error_is_a_failure():
    """THE DEFECT. Captured from mission 6a7c5991: three cells raised
    SyntaxError and every one arrived with isError=false."""
    event = _end(is_error=False, status="error", ename="SyntaxError")
    assert classify_tool_execution(event) == "error"


def test_a_run_where_every_kernel_execution_failed_did_no_real_work():
    outcome = SessionOutcome(
        state=SessionState.COMPLETED,
        final_answer="Root cause: connection pool exhaustion. Incident resolved.",
        tool_execution_count=4,
        tool_success_count=0,
        tool_error_count=4,
    )
    assert outcome.did_real_work is False


def test_a_confident_final_answer_does_not_rescue_a_run_that_did_nothing():
    """The agent's narrative is not a parameter of the verdict. This run's
    real final answer claimed the incident was 'resolved… while maintaining
    SLA compliance' — none of which happened."""
    outcome = SessionOutcome(
        state=SessionState.COMPLETED,
        final_answer=(
            "The ADOS system successfully created a ServiceNow incident to address "
            "the critical 502 error spike. The root cause was identified and the "
            "incident has been resolved while maintaining SLA compliance. 🟢"
        ),
        tool_execution_count=4,
        tool_success_count=0,
        tool_error_count=4,
    )
    verdict = evaluate_mission(
        outcome=outcome,
        executed_capabilities=[],
        required_capabilities=["FetchIncidentEvidence", "NotifyITHelpdesk"],
    )
    assert verdict.succeeded is False
    assert "could not act" in verdict.summary

    # And the same run with a blank answer is rejected for the same reason —
    # the text is not consulted in either direction.
    assert evaluate_mission(
        outcome=replace(outcome, final_answer=None),
        executed_capabilities=[],
        required_capabilities=["FetchIncidentEvidence"],
    ).reasons[0] == verdict.reasons[0]


# --- the negative control ----------------------------------------------------

def test_the_old_isError_only_rule_would_pass_this():
    """Restores the old rule and shows it scoring a wholly failed run as 4/4.

    Without this, the tests above prove only that the new code agrees with
    itself. This pins what the fix actually changed: the same four events, the
    same session, two different verdicts.
    """
    events = [
        _end(is_error=False, status="error", ename="SyntaxError"),
        _end(is_error=False, status="error", ename="SyntaxError"),
        _end(is_error=False, status="error", ename="SyntaxError"),
        _end(is_error=False, status="error", ename="SyntaxError"),
    ]

    def old_rule(event):  # the code as it was, verbatim in spirit
        return "error" if event.get("isError") else "ok"

    old_ok = sum(1 for e in events if old_rule(e) == "ok")
    new_ok = sum(1 for e in events if classify_tool_execution(e) == "ok")

    assert old_ok == 4, "the old rule really did score every SyntaxError as a success"
    assert new_ok == 0

    # ...and the consequence, which is the part that mattered:
    assert SessionOutcome(
        state=SessionState.COMPLETED, tool_execution_count=4, tool_success_count=old_ok
    ).did_real_work is True
    assert SessionOutcome(
        state=SessionState.COMPLETED, tool_execution_count=4, tool_success_count=new_ok,
        tool_error_count=4,
    ).did_real_work is False


# --- the rest of the surface -------------------------------------------------

def test_a_thrown_tool_call_is_a_failure_even_with_no_status():
    """Prime Agent's throw path: createErrorToolResult returns `details: {}`
    and the core sets isError=true. Captured from diag_events.jsonl."""
    event = {
        "type": "tool_execution_end", "toolName": "ipython", "toolCallId": "c",
        "result": {"content": [{"type": "text", "text": "Tool execution aborted"}], "details": {}},
        "isError": True,
    }
    assert classify_tool_execution(event) == "error"


def test_aborted_is_a_failure():
    assert classify_tool_execution(_end(status="aborted")) == "error"


@pytest.mark.parametrize("event", [
    {"type": "tool_execution_end", "isError": False},                      # no result at all
    {"type": "tool_execution_end", "isError": False, "result": "a string"},  # wrong shape
    _end(status=None),                                                     # no verdict
    _end(status="something-upstream-added"),                               # unrecognised
])
def test_a_result_with_no_verdict_ados_recognises_is_never_a_success(event):
    """The standing invariant: never infer success from the absence of an
    error. An unknown counts toward neither successes nor failures."""
    assert classify_tool_execution(event) == "unknown"


def test_the_tools_own_flag_is_consulted_for_failure_but_never_for_success():
    """`result.isError` survives unless a tool_result extension hook rewrote
    the result. Worth reading to find a failure; not enough to claim success."""
    assert classify_tool_execution(_end(status=None, result_is_error=True)) == "error"
    assert classify_tool_execution(_end(status=None, result_is_error=False)) == "unknown"


def test_unknown_executions_are_not_counted_as_work_done():
    outcome = SessionOutcome(
        state=SessionState.COMPLETED, final_answer="done",
        tool_execution_count=3, tool_success_count=0, tool_error_count=0,
        tool_unknown_count=3,
    )
    assert outcome.did_real_work is False
    verdict = evaluate_mission(outcome=outcome, executed_capabilities=[], required_capabilities=[])
    assert verdict.succeeded is False
    assert "3 indeterminate" in verdict.summary
    assert verdict.observed["tool_indeterminate"] == 3


def test_the_audit_row_records_the_kernel_verdict_and_the_raw_flag():
    """Both, deliberately. The two disagreeing is the signature of this defect,
    and a row showing only the corrected value hides that it ever happened."""
    detail = PrimeAgentRuntime._event_detail(
        _end(is_error=False, status="error", ename="SyntaxError")
    )
    assert detail["kernel_verdict"] == "error"
    assert detail["kernel_status"] == "error"
    assert detail["kernel_error"] == "SyntaxError"
    assert detail["isError"] is False


def test_a_successful_execution_records_its_verdict_too():
    detail = PrimeAgentRuntime._event_detail(_end(is_error=False, status="ok"))
    assert detail["kernel_verdict"] == "ok"
    assert detail["kernel_status"] == "ok"
    assert "kernel_error" not in detail


# --- the wiring --------------------------------------------------------------
#
# Everything above tests the classifier. These drive run_objective's own event
# loop, because a correct classifier that the loop does not call would leave the
# defect exactly where it was.

async def _run_with_events(monkeypatch, events):
    """Drive run_objective over a canned event stream, no container involved."""
    class _FakeProc:
        def __init__(self):
            self.stdin = self
            self.returncode = 0

        def write(self, _data):  # stdin.write
            pass

        async def drain(self):
            pass

        async def wait(self):
            return 0

        def kill(self):
            pass

    async def _fake_exec(*_args, **_kwargs):
        return _FakeProc()

    async def _fake_read_events(self, _proc, _timeout):
        for event in events:
            yield event

    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(PrimeAgentRuntime, "_read_events", _fake_read_events)
    monkeypatch.setattr(PrimeAgentRuntime, "recover_runtime_session_id", lambda self: None)

    runtime = PrimeAgentRuntime(mcp_url="http://example/mcp/")
    runtime.container_name = "fake-container"
    spec = AgentSessionSpec(
        mission_id="m", session_id="s", objective="o", success_criteria="c",
        allowed_capabilities=[], workspace_files={}, max_wall_clock_seconds=5.0,
    )
    return await runtime.run_objective(spec)


def _start(tool="ipython"):
    return {"type": "tool_execution_start", "toolName": tool, "toolCallId": "call_x"}


def _agent_end(text="Root cause identified and the incident is resolved."):
    return {
        "type": "agent_end",
        "messages": [{"role": "assistant", "content": [{"type": "text", "text": text}]}],
    }


async def test_run_objective_counts_kernel_errors_as_errors(monkeypatch):
    """The production trace, reproduced: four cells, three SyntaxErrors."""
    outcome = await _run_with_events(monkeypatch, [
        _start(), _end(status="error", ename="SyntaxError"),
        _start(), _end(status="error", ename="SyntaxError"),
        _start(), _end(status="error", ename="SyntaxError"),
        _start(), _end(status="ok"),
        _agent_end(),
    ])
    assert outcome.tool_execution_count == 4
    assert (outcome.tool_success_count, outcome.tool_error_count) == (1, 3)
    assert outcome.did_real_work is True  # one cell really did run


async def test_a_session_where_every_cell_raised_is_failed_however_fluent(monkeypatch):
    """The case the whole fix exists for: the agent ends cleanly, with a
    confident answer, having executed nothing."""
    outcome = await _run_with_events(monkeypatch, [
        _start(), _end(status="error", ename="SyntaxError"),
        _start(), _end(status="error", ename="NameError"),
        _agent_end("The incident was resolved and the helpdesk has been notified."),
    ])
    assert outcome.state is SessionState.FAILED
    assert outcome.did_real_work is False
    assert "none of 2 kernel tool executions succeeded" in outcome.failure_reason
    assert "2 failed" in outcome.failure_reason


async def test_indeterminate_executions_are_reported_separately(monkeypatch):
    outcome = await _run_with_events(monkeypatch, [
        _start(), _end(status=None),
        _agent_end(),
    ])
    assert (outcome.tool_success_count, outcome.tool_error_count) == (0, 0)
    assert outcome.tool_unknown_count == 1
    assert outcome.state is SessionState.FAILED
    assert "1 indeterminate" in outcome.failure_reason


async def test_a_clean_run_still_completes(monkeypatch):
    """The fix must not make working runs fail — the point is a stronger
    invariant, not a stricter one."""
    outcome = await _run_with_events(monkeypatch, [
        _start(), _end(status="ok"),
        _start(), _end(status="ok"),
        _agent_end(),
    ])
    assert outcome.state is SessionState.COMPLETED
    assert (outcome.tool_success_count, outcome.tool_error_count, outcome.tool_unknown_count) == (2, 0, 0)
