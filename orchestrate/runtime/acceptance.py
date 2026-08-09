"""
Mission acceptance — the one place ADOS decides whether a mission succeeded.

THE INVARIANT
-------------
    An agent's narrative is never authoritative evidence.

"Root cause is X" is a claim, not a result. It is worth storing, showing to a
human, and reasoning about later; it is never a reason to mark a mission
complete. Truth about a mission comes from things ADOS observed or performed:

    * governed capability executions ADOS itself carried out
    * evidence ADOS served through those capabilities
    * connector results
    * independently verifiable effects
    * persisted artifacts

This is not a theoretical safeguard. A runtime whose kernel could not execute a
single statement produced a detailed, fluent root-cause report attributing a
checkout outage to disk-space exhaustion on a database server — a system, a
symptom, and an error string that appear nowhere in the incident it was given
and never managed to read. Nothing about the prose gave it away. What gave it
away was that ADOS had executed no capability for that mission.

So the family of confusions this module refuses to make, each of which has cost
a real debugging session here:

    tool attempt      != tool success
    process exit 0    != mission success
    HTTP 200          != capability success
    agent narrative   != evidence
    model completion  != mission completion

`evaluate_mission` takes no argument derived from anything the agent wrote. The
final answer is not a parameter. That is deliberate and load-bearing: an
acceptance function that cannot see the narrative cannot be persuaded by it, and
a future change that wants to consult it has to alter this signature in a
diff a reviewer will notice.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from .base import SessionOutcome, SessionState


@dataclass(frozen=True)
class MissionVerdict:
    """Why ADOS believes what it believes, kept alongside the answer.

    `reasons` is populated on failure and is meant to be readable by whoever
    picks the mission up next — "the runtime could not act" and "the runtime
    acted but never did the thing that was asked" are very different situations
    and should not both surface as a bare False.
    """

    succeeded: bool
    reasons: List[str] = field(default_factory=list)
    observed: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return "mission accepted" if self.succeeded else "; ".join(self.reasons)


def evaluate_mission(
    *,
    outcome: SessionOutcome,
    executed_capabilities: Sequence[str],
    required_capabilities: Iterable[str] = (),
) -> MissionVerdict:
    """Decide a mission's fate from observed effects alone.

    Args:
        outcome: what the runtime adapter OBSERVED — counts of tool executions
            that succeeded and failed, and the terminal session state. Not what
            the agent said about itself.
        executed_capabilities: capability names ADOS actually executed for this
            mission, read from `capability_requests` where status='executed'.
            These rows are written by the gateway that performed the call, so
            they cannot be produced by an agent claiming to have acted.
        required_capabilities: what this mission is not complete without.

    There is intentionally no `final_answer`, no `report`, and no `confidence`
    parameter. See the module docstring.
    """
    reasons: List[str] = []
    executed = list(executed_capabilities)

    # 1. Did the runtime do anything at all? A run with tool attempts but zero
    #    successes is a runtime that could not act — and is exactly the state in
    #    which agents produce their most confident fiction, because a broken
    #    tool still leaves the model free to write.
    if outcome.tool_execution_count == 0:
        reasons.append("the runtime produced no kernel tool executions — it did nothing")
    elif not outcome.did_real_work:
        reasons.append(
            f"none of {outcome.tool_execution_count} kernel tool executions succeeded "
            f"({outcome.tool_error_count} failed, {outcome.tool_unknown_count} indeterminate) — "
            "the runtime could not act, so any report it produced is unsourced"
        )

    # 2. Did the required governed work actually happen? This is the check that
    #    a fabricated report cannot pass, because it is answered from ADOS's own
    #    rows rather than from the runtime's account of itself.
    missing = [c for c in required_capabilities if c not in executed]
    if missing:
        reasons.append(
            f"required capabilities were never executed by ADOS: {', '.join(missing)}"
        )

    # 3. Did the session end cleanly? Last, not first: a clean exit proves
    #    nothing on its own, and ordering it after the effect checks keeps that
    #    obvious to anyone reading the failure reasons.
    if outcome.state is not SessionState.COMPLETED:
        reasons.append(f"runtime session ended in state '{outcome.state.value}'")

    return MissionVerdict(
        succeeded=not reasons,
        reasons=reasons,
        observed={
            "tool_executions": outcome.tool_execution_count,
            "tool_successes": outcome.tool_success_count,
            "tool_errors": outcome.tool_error_count,
            "tool_indeterminate": outcome.tool_unknown_count,
            "capabilities_executed_by_ados": executed,
            "required_capabilities": list(required_capabilities),
            "session_state": outcome.state.value,
        },
    )
