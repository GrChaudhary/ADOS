"""
Incident state machine — the transition graph from
docs/005-decision-orchestrator.md's diagram, enforced here rather than
left implicit in DecisionOrchestrator's control flow.
"""

from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple

from contracts import IncidentState

_TRANSITIONS: Dict[IncidentState, Set[IncidentState]] = {
    IncidentState.DETECTED: {IncidentState.DIAGNOSING},
    IncidentState.DIAGNOSING: {
        IncidentState.CANDIDATE_GENERATION,
        IncidentState.FAILED,
        IncidentState.PREEMPTED,
    },
    IncidentState.CANDIDATE_GENERATION: {
        IncidentState.RESERVING,
        IncidentState.FAILED,
        IncidentState.PREEMPTED,
    },
    IncidentState.RESERVING: {
        IncidentState.AWAITING_APPROVAL,
        IncidentState.FAILED,
        IncidentState.PREEMPTED,
    },
    IncidentState.AWAITING_APPROVAL: {
        IncidentState.EXECUTING,
        IncidentState.ESCALATED,
        IncidentState.FAILED,
    },
    IncidentState.ESCALATED: {IncidentState.AWAITING_APPROVAL},
    IncidentState.EXECUTING: {IncidentState.RESOLVED, IncidentState.FAILED},
    # Resuming a Preempted incident restarts diagnosis (docs/005) — resume
    # itself isn't implemented yet (see orchestrate/README.md), only the
    # state graph allows it so a future resume path isn't blocked here.
    IncidentState.PREEMPTED: {IncidentState.DIAGNOSING},
    IncidentState.RESOLVED: set(),
    IncidentState.FAILED: set(),
}


class InvalidTransition(Exception):
    def __init__(self, from_state: IncidentState, to_state: IncidentState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"illegal transition {from_state.value} -> {to_state.value}")


class IncidentStateMachine:
    def __init__(self, initial: IncidentState = IncidentState.DETECTED):
        self.state = initial
        self.history: List[Tuple[IncidentState, str]] = [
            (initial, datetime.now(timezone.utc).isoformat())
        ]

    def transition(self, to_state: IncidentState) -> None:
        if to_state not in _TRANSITIONS.get(self.state, set()):
            raise InvalidTransition(self.state, to_state)
        self.state = to_state
        self.history.append((to_state, datetime.now(timezone.utc).isoformat()))

    def is_terminal(self) -> bool:
        return self.state in (IncidentState.RESOLVED, IncidentState.FAILED)
