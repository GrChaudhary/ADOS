"""
Standalone demo — mirrors scripts/run_orchestrator_demo.py's style, but
through the LangGraph slice instead of the real orchestrator. Runs the
same canonical scenario, auto-approves the Tier 1 gate, prints the result.

Run: .venv/bin/python -m orchestrate_langgraph.demo
"""

import asyncio

from .graph import resume_incident_langgraph, run_incident_langgraph
from .scenario_defaults import SCENARIO


async def main() -> None:
    print(f"Running canonical scenario through orchestrate_langgraph: {SCENARIO}\n")

    record, graph, config = await run_incident_langgraph(**SCENARIO, incident_id="demo-langgraph-1")

    if record is None:
        snapshot = await graph.aget_state(config)
        interrupt_payload = snapshot.tasks[0].interrupts[0].value
        print(f"Paused for approval at {snapshot.next}: {interrupt_payload}\n")
        print("Auto-approving as 'ops-lead-demo'...\n")
        record = await resume_incident_langgraph(graph, config, decision="approved", approved_by="ops-lead-demo")

    print("Final IncidentRecord:")
    for key, value in record.model_dump(by_alias=True).items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
