"""
Cascade Circuit Breaker — orchestration-platform-vision.md §5.3. Even when
every individual action passes its own governance check, a long chain of
individually-"safe" (Tier 0 / autonomous) actions can add up to something
nobody actually approved as a whole — e.g. 15 small auto-approved steps
that together fully de-provision an employee with no human ever seeing the
big picture. This tracks consecutive auto-approved actions within one task
and forces a human to review the full batch before more autonomous
execution continues, independent of whether any single action tripped its
own flag.

Deliberately in-memory and scoped to one incident/task, not Redis-backed:
unlike a reliability circuit breaker (the CLOSED/OPEN state-machine shape
here is adapted from one seen in agentic-org's connectors/framework/
circuit_breaker.py), this isn't a cross-process reliability signal, it's a
per-task governance gate — and ADOS's orchestrator already runs each
incident's lifecycle as a single in-process coroutine (see ApprovalQueue's
asyncio.Event in governance.py). Redis would add cross-process durability
nothing here currently needs.

Also unlike a reliability breaker, there is deliberately no timed
auto-recovery. A reliability breaker reopens after a timeout because the
failing dependency might have healed on its own; here the entire point is
that a human has to look at the batch — waiting out a clock doesn't
substitute for that, so only clear_after_review() (an explicit human
action) resets the breaker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class CascadeState(str, Enum):
    CLOSED = "closed"  # proceeding normally
    OPEN = "open"  # paused — batch awaiting human review


class CascadeBreakerOpen(RuntimeError):
    def __init__(self, streak: List["AutoApprovedAction"]):
        self.streak = streak
        super().__init__(
            f"cascade breaker is open — {len(streak)} auto-approved actions awaiting human review before continuing"
        )


@dataclass(frozen=True)
class AutoApprovedAction:
    capability: str
    summary: str


@dataclass
class CascadeCircuitBreaker:
    """One instance per incident/task. threshold default per vision §5.3
    ("Starting default: N = 3-5, tunable by admin")."""

    threshold: int = 4
    state: CascadeState = CascadeState.CLOSED
    _streak: List[AutoApprovedAction] = field(default_factory=list)

    def record_auto_approved(self, capability: str, summary: str) -> CascadeState:
        """Call this every time an action is about to execute autonomously
        (Tier 0). Raises CascadeBreakerOpen if the breaker is already open
        — the caller must not execute the action, it must route to human
        review instead."""
        if self.state is CascadeState.OPEN:
            raise CascadeBreakerOpen(list(self._streak))
        self._streak.append(AutoApprovedAction(capability, summary))
        if len(self._streak) >= self.threshold:
            self.state = CascadeState.OPEN
        return self.state

    def record_human_decision(self) -> None:
        """A Tier 1/2 action that actually went through human approval
        breaks the streak too — §5.3's concern is a run of *unseen*
        actions, and a human just saw one, so the cascade risk resets."""
        self._streak.clear()
        if self.state is CascadeState.OPEN:
            self.state = CascadeState.CLOSED

    def review_batch(self) -> List[AutoApprovedAction]:
        """What a human sees when the breaker is open — the full run of
        auto-approved actions that triggered the pause."""
        return list(self._streak)

    def clear_after_review(self) -> None:
        """Explicit human sign-off on the batch. No timeout-based
        auto-recovery — see module docstring."""
        self._streak.clear()
        self.state = CascadeState.CLOSED
