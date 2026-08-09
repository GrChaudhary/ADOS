"""
The runtime boundary: what ADOS knows about *any* execution runtime, with no
Prime Agent specifics leaking in.

ADOS mission logic depends on this module. `prime.py` is one implementation.
Anything Prime-shaped (RPC framing, IPython kernels, container names) belongs
there, not here.

Only operations the underlying runtime genuinely supports are modelled. Prime
Agent has no suspend primitive, so there is no `pause()` — a mission waiting on
a human is a state of the ADOS *session row* while the agent polls, not a
frozen process. Inventing `pause()` here would be a lie the implementation
could not keep.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SessionState(str, Enum):
    """Lifecycle of one runtime session. Persisted on RuntimeSessionRow so ADOS
    can still say what happened after the container is gone."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    # The agent asked ADOS for a capability and is blocked on the answer.
    WAITING_FOR_CAPABILITY = "waiting_for_capability"
    # That capability needs a human. Distinct from the above because the wait
    # is unbounded and the recovery is different: a person must act.
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Container removed and workspace deleted. Terminal for resources, not for
    # the record: the row and its events survive.
    TORN_DOWN = "torn_down"


TERMINAL_STATES = {SessionState.COMPLETED, SessionState.FAILED, SessionState.CANCELLED}


@dataclass
class AgentSessionSpec:
    """Everything a runtime is told. Note what is absent: no database URL, no
    connector credentials, no ADOS user identity. A runtime receives an
    objective, a workspace, and a session credential that is identity-only."""

    mission_id: str
    session_id: str
    objective: str
    success_criteria: str = ""
    # Advisory only — echoed to the agent so it knows what to ask for. The
    # gateway re-resolves the real grant server-side on every call and never
    # trusts anything the runtime presents.
    allowed_capabilities: List[str] = field(default_factory=list)
    workspace_files: Dict[str, str] = field(default_factory=dict)
    max_wall_clock_seconds: float = 900.0


@dataclass
class RuntimeEvent:
    """A runtime event normalized into ADOS's vocabulary, so nothing downstream
    parses Prime Agent's shapes."""

    type: str
    at: str
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionOutcome:
    """The result of a run, and the evidence for believing it.

    `succeeded` is deliberately NOT derived from the process exit code, an HTTP
    status, or the absence of an exception. A model was observed emitting
    `agent_end` with empty content, zero tool executions and exit 0 — a clean
    report of having done nothing. Success is asserted from observed effects:
    kernel tool executions, capability requests ADOS actually recorded, and a
    final answer.
    """

    state: SessionState
    final_answer: Optional[str] = None
    events: List[RuntimeEvent] = field(default_factory=list)
    tool_execution_count: int = 0
    # Split out, because "it called its tool" and "its tool worked" are very
    # different claims. A run was observed with 7 tool executions where every
    # single one returned isError=true: the agent could do nothing, wrote a
    # lucid explanation of why, and an earlier version of this class scored
    # that as a completed mission. Counting attempts is not counting work.
    tool_success_count: int = 0
    tool_error_count: int = 0
    capability_request_count: int = 0
    failure_reason: Optional[str] = None
    runtime_session_id: Optional[str] = None

    @property
    def did_real_work(self) -> bool:
        """Did anything actually SUCCEED inside the runtime?"""
        return self.tool_success_count > 0
