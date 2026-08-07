"""
Per-mechanism latency benchmark — see COMPARISON.md's Latency & Cost
section for why this deliberately does NOT report a whole-incident total
(the slice runs 4 of the custom engine's 8 stages, so a whole-incident
number would conflate "faster framework" with "fewer stages run").

Each mechanism isolates ONE piece of framework overhead by holding the
underlying agent/call identical on both sides and varying only how it's
invoked — via AgentRunner.run_stage() (custom) vs. a LangGraph node
(via a minimal single-node graph, so timing isolates that one node's
dispatch cost rather than the whole 5-node pipeline's).

Run: .venv/bin/python -m orchestrate_langgraph.bench_latency
Writes orchestrate_langgraph/bench_results.json.
"""

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Callable, Dict, List

# See nodes.py's NOTE on import order — orchestrate must be touched
# before a bare `from agents import ...` for this module to be safely
# importable standalone (e.g. via `python -m orchestrate_langgraph.bench_latency`).
from orchestrate.agent_runner import AgentRunner
from orchestrate.governance import PendingApproval

from agents import CausalIsolationAgent, VisionSpecAgent
from agents.sdk import IncidentContext, StageInput
from backend.app.eventbus import InMemoryEventBus
from contracts import CapabilityCall, GovernanceInfo, PolicyTier
from integrations import IntegrationHub
from integrations.connectors.console import ConsoleConnector
from knowledge import CausalGraph, DigitalTwinStore, KnowledgeGraph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .nodes import causal_isolation_node, execute_capability_node, vision_spec_node
from .scenario_defaults import SCENARIO, SLICE_CAPABILITY, SLICE_ESTIMATED_COST_USD
from .state import IncidentGraphState

N = 50


def _stats(samples_s: List[float]) -> Dict[str, float]:
    samples_ms = sorted(s * 1000 for s in samples_s)
    return {
        "n": len(samples_ms),
        "mean_ms": round(statistics.mean(samples_ms), 3),
        "p50_ms": round(statistics.median(samples_ms), 3),
        "p95_ms": round(samples_ms[int(len(samples_ms) * 0.95) - 1], 3),
    }


async def _time_n(fn: Callable[[], "asyncio.Future"], n: int = N) -> List[float]:
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        await fn()
        samples.append(time.perf_counter() - start)
    return samples


def _single_node_graph(node_fn):
    builder = StateGraph(IncidentGraphState)
    builder.add_node("only", node_fn)
    builder.add_edge(START, "only")
    builder.add_edge("only", END)
    return builder.compile(checkpointer=InMemorySaver())


async def mechanism_a() -> Dict[str, Dict[str, float]]:
    """Deterministic node overhead: VisionSpecAgent."""
    bus = InMemoryEventBus()
    runner = AgentRunner(bus, KnowledgeGraph(), CausalGraph(), DigitalTwinStore())
    ctx = IncidentContext(
        incident_id="bench", plant_id=SCENARIO["plant_id"], line_id=SCENARIO["line_id"],
        part_number=SCENARIO["part_number"],
    )
    stage_input = StageInput(
        stage_name="Perception",
        payload={"vision_data": SCENARIO["vision_data"], "part_number": SCENARIO["part_number"]},
    )

    async def custom_call():
        await runner.run_stage("vision_spec", ctx, stage_input)

    graph = _single_node_graph(vision_spec_node)
    counter = {"i": 0}

    async def langgraph_call():
        counter["i"] += 1
        config = {"configurable": {"thread_id": f"bench-a-{counter['i']}"}}
        initial: IncidentGraphState = {
            "incident_id": "bench", "plant_id": SCENARIO["plant_id"], "line_id": SCENARIO["line_id"],
            "part_number": SCENARIO["part_number"], "vision_data": SCENARIO["vision_data"],
        }
        await graph.ainvoke(initial, config=config)

    return {"custom_engine": _stats(await _time_n(custom_call)), "langgraph": _stats(await _time_n(langgraph_call))}


async def mechanism_b() -> Dict[str, Dict[str, float]]:
    """'LLM-backed' node overhead: CausalIsolationAgent. LLM is disabled by
    default in this environment (conftest.py-equivalent gate), so this
    measures framework overhead around the identical rule-based fallback
    path, NOT real LLM latency — see COMPARISON.md."""
    bus = InMemoryEventBus()
    runner = AgentRunner(bus, KnowledgeGraph(), CausalGraph(), DigitalTwinStore())
    ctx = IncidentContext(
        incident_id="bench", plant_id=SCENARIO["plant_id"], line_id=SCENARIO["line_id"],
        part_number=SCENARIO["part_number"],
    )
    stage_input = StageInput(stage_name="Reasoning", payload={"defect_type": "dimensional fault"})

    async def custom_call():
        await runner.run_stage("causal_isolation", ctx, stage_input)

    graph = _single_node_graph(causal_isolation_node)
    counter = {"i": 0}

    async def langgraph_call():
        counter["i"] += 1
        config = {"configurable": {"thread_id": f"bench-b-{counter['i']}"}}
        initial: IncidentGraphState = {
            "incident_id": "bench", "plant_id": SCENARIO["plant_id"], "line_id": SCENARIO["line_id"],
            "part_number": SCENARIO["part_number"], "vision_result": {"defect_type": "dimensional fault"},
        }
        await graph.ainvoke(initial, config=config)

    return {"custom_engine": _stats(await _time_n(custom_call)), "langgraph": _stats(await _time_n(langgraph_call))}


async def mechanism_c() -> Dict[str, Dict[str, float]]:
    """Approval pause+resume: PendingApproval.resolve()->asyncio.Event
    wakeup vs. Command(resume=...)->graph.ainvoke() re-entry (which
    re-executes the interrupting node from its top)."""

    async def custom_call():
        pending = PendingApproval(
            incident_id="bench", capability=SLICE_CAPABILITY, policy_tier=PolicyTier.APPROVAL_REQUIRED,
            confidence=0.84, summary="bench", estimated_cost_usd=SLICE_ESTIMATED_COST_USD,
        )
        waiter = asyncio.create_task(pending.wait())
        await asyncio.sleep(0)  # let the waiter actually start waiting
        pending.resolve("approved", "bench")
        await waiter

    def gate_node(state):
        d = interrupt({"ask": "approve?"})
        return {"approval_decision": d["decision"]}

    builder = StateGraph(IncidentGraphState)
    builder.add_node("gate", gate_node)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    counter = {"i": 0}

    async def langgraph_call():
        counter["i"] += 1
        config = {"configurable": {"thread_id": f"bench-c-{counter['i']}"}}
        await graph.ainvoke({}, config=config)  # reach the interrupt (untimed setup happens inside _time_n anyway)
        await graph.ainvoke(Command(resume={"decision": "approved"}), config=config)

    # For C, only the RESUME half is the mechanism of interest, but the
    # pause-then-resume round trip is what a caller actually experiences,
    # so both halves are timed together on the LangGraph side (same as the
    # custom side times create+resolve+wakeup together) for a fair
    # like-for-like "full round trip" comparison.
    return {"custom_engine": _stats(await _time_n(custom_call)), "langgraph": _stats(await _time_n(langgraph_call))}


async def mechanism_d() -> Dict[str, Dict[str, float]]:
    """Mocked capability execution overhead. IntegrationHub.invoke() with
    ConsoleConnector is byte-identical on both sides (orchestrator.py calls
    it directly, not through AgentRunner, so the custom baseline here is
    the raw call, not a run_stage() wrapper) — this isolates LangGraph's
    node-dispatch overhead specifically."""

    def _call():
        hub = IntegrationHub()
        hub.registry.register(ConsoleConnector())
        return hub, CapabilityCall(
            capability=SLICE_CAPABILITY, incident_id="bench", requested_by="bench",
            input={"execution_steps": ["x"], "target_line_id": SCENARIO["line_id"]},
            governance=GovernanceInfo(policy_tier=PolicyTier.APPROVAL_REQUIRED, approved_by="bench"),
        )

    async def custom_call():
        hub, call = _call()
        await hub.invoke(call)

    graph = _single_node_graph(execute_capability_node)
    counter = {"i": 0}

    async def langgraph_call():
        counter["i"] += 1
        config = {"configurable": {"thread_id": f"bench-d-{counter['i']}"}}
        initial: IncidentGraphState = {
            "incident_id": "bench", "line_id": SCENARIO["line_id"], "policy_tier": PolicyTier.APPROVAL_REQUIRED.value,
            "approved_by": "bench",
        }
        await graph.ainvoke(initial, config=config)

    return {"custom_engine": _stats(await _time_n(custom_call)), "langgraph": _stats(await _time_n(langgraph_call))}


async def main() -> Dict[str, Dict[str, Dict[str, float]]]:
    results = {
        "A_deterministic_node_vision_spec": await mechanism_a(),
        "B_llm_backed_node_causal_isolation_fallback_path": await mechanism_b(),
        "C_approval_pause_resume_round_trip": await mechanism_c(),
        "D_mocked_capability_execution": await mechanism_d(),
    }
    out_path = Path(__file__).parent / "bench_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\nWrote {out_path}")
    return results


if __name__ == "__main__":
    asyncio.run(main())
