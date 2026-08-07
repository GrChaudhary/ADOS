"""
AgentRunner.run_stage() must not block the event loop, and must not let
concurrent incidents race on shared mutable state.

Both properties are load-bearing and they pull against each other, so they
are pinned together here:

- Before this, `agent.run()` was called directly from an async method. The
  LLM-backed agents spend up to 90 seconds inside a blocking
  httpx.Client call, so one incident's reasoning froze the whole API.
- But the agents share one KnowledgeGraph/CausalGraph/DigitalTwinStore, and
  two of them mutate it (CausalGraph.recalibrate_weight writes _edges;
  DigitalTwinStore.reserve_line_capacity appends to soft_reservations).
  Offloading to a thread without serialising would have replaced a hung
  event loop with a data race.
"""

import asyncio
import time

import pytest

from agents.sdk import IncidentContext, StageInput
from backend.app.eventbus.memory_bus import InMemoryEventBus
from contracts import EventEnvelope
from knowledge import CausalGraph, DigitalTwinStore, KnowledgeGraph
from orchestrate.agent_runner import AgentRunner

_BLOCKING_SECONDS = 0.3


def _runner() -> AgentRunner:
    return AgentRunner(
        event_bus=InMemoryEventBus(),
        knowledge_graph=KnowledgeGraph(),
        causal_graph=CausalGraph(),
        digital_twin=DigitalTwinStore(),
    )


class _BlockingAgent:
    """Stands in for an LLM-backed agent: a synchronous call that sleeps the
    way a real blocking HTTP request would."""

    agent_id = "blocking-test-agent"

    def __init__(self):
        self.concurrent_calls = 0
        self.max_observed_concurrency = 0

    def run(self, context, stage_input):
        self.concurrent_calls += 1
        self.max_observed_concurrency = max(
            self.max_observed_concurrency, self.concurrent_calls
        )
        time.sleep(_BLOCKING_SECONDS)  # deliberately blocking, like httpx.Client
        self.concurrent_calls -= 1
        return (
            StageOutputStub(),
            EventEnvelope(
                event_type="AgentCompleted",
                correlation_id=context.incident_id,
                produced_by="test",
                payload={},
            ),
        )


class StageOutputStub:
    result = {}
    confidence = 1.0
    evidence = []
    alternatives = []


def _context() -> IncidentContext:
    return IncidentContext(
        incident_id="INC-CONCURRENCY-TEST", plant_id="PLANT-1", line_id="LINE-1"
    )


def _stage_input() -> StageInput:
    return StageInput(stage_name="Perception", payload={})


@pytest.mark.asyncio
async def test_run_stage_does_not_block_the_event_loop():
    """The property that matters to every other user of the API: while an
    agent is doing its slow synchronous work, the event loop must still be
    free to run other coroutines.

    Fails against the old code -- a direct agent.run() call starves the
    ticker completely, so it records ~0 ticks.
    """
    runner = _runner()
    runner._agents["blocking"] = _BlockingAgent()

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    ticker_task = asyncio.create_task(ticker())
    try:
        await runner.run_stage("blocking", _context(), _stage_input())
    finally:
        ticker_task.cancel()

    # ~30 ticks are theoretically possible in 0.3s; anything clearly above
    # zero proves the loop kept running. Deliberately loose so this doesn't
    # become a flaky timing test on a loaded CI runner.
    assert ticks > 5, f"event loop was starved during agent.run() (only {ticks} ticks)"


@pytest.mark.asyncio
async def test_concurrent_stages_never_run_an_agent_in_parallel():
    """Two incidents in flight at once must not execute agent code
    simultaneously, because the agents share mutable graph/twin state with no
    internal locking. This is what stops the fix above from introducing a
    data race."""
    runner = _runner()
    agent = _BlockingAgent()
    runner._agents["blocking"] = agent

    await asyncio.gather(
        runner.run_stage("blocking", _context(), _stage_input()),
        runner.run_stage("blocking", _context(), _stage_input()),
        runner.run_stage("blocking", _context(), _stage_input()),
    )

    assert agent.max_observed_concurrency == 1, (
        "agents ran concurrently -- shared CausalGraph/DigitalTwinStore state "
        f"is unprotected (observed {agent.max_observed_concurrency} at once)"
    )
