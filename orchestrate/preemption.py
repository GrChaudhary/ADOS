"""
Preemption engine — docs/005-decision-orchestrator.md: "the lower-priority
incident transitions to Preempted... once the resource frees up" when two
incidents compete for the same line. Tracks one occupant per line_id;
starting a higher-priority incident on an already-occupied line signals
the occupant's preempt_event, which DecisionOrchestrator checks at each
state-machine transition (see agent_runner.py's docstring on why
preemption happens between states, not mid-agent-call).

Also backs auto-resume: wait_for_line_free() lets a bumped incident wait
for the line to actually free up before retrying, rather than the caller
polling — DecisionOrchestrator.run_incident() awaits this after a
preemption before restarting diagnosis under the same incident_id.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class LineOccupant:
    incident_id: str
    priority_score: float
    preempt_event: asyncio.Event = field(default_factory=asyncio.Event)


class PreemptionEngine:
    def __init__(self):
        self._occupants: Dict[str, LineOccupant] = {}
        self._freed: Dict[str, asyncio.Event] = {}

    def _freed_event(self, line_id: str) -> asyncio.Event:
        if line_id not in self._freed:
            self._freed[line_id] = asyncio.Event()
        return self._freed[line_id]

    def claim_or_preempt(self, line_id: str, incident_id: str, priority_score: float) -> Optional[LineOccupant]:
        """Attempt to claim `line_id` for `incident_id`. Returns the
        occupant record for the caller to hold onto (check
        `.preempt_event` at each state transition), or None if a
        higher-or-equal-priority incident already holds the line — in
        which case the caller should wait_for_line_free() and retry."""
        current = self._occupants.get(line_id)
        if current is not None and current.priority_score >= priority_score:
            return None
        if current is not None:
            current.preempt_event.set()

        occupant = LineOccupant(incident_id=incident_id, priority_score=priority_score)
        self._occupants[line_id] = occupant
        self._freed_event(line_id).clear()
        return occupant

    def release(self, line_id: str, incident_id: str) -> None:
        current = self._occupants.get(line_id)
        if current is not None and current.incident_id == incident_id:
            del self._occupants[line_id]
            self._freed_event(line_id).set()

    async def wait_for_line_free(self, line_id: str) -> None:
        await self._freed_event(line_id).wait()
