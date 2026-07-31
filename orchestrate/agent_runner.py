"""
Agent runner — the orchestrator's bridge to the Phase 2 agent roster
(agents/). docs/005-decision-orchestrator.md: the orchestrator sequences
stages via the event bus rather than calling agents synchronously.

MVP fidelity note: each agent's `.run()` (agents/sdk/base.py) is itself a
synchronous call that already builds the AgentCompleted EventEnvelope, so
"via the event bus" here means every stage both (a) announces itself with
a StageRequested event before running and (b) publishes the agent's
AgentCompleted event after — giving the full observability/replayability
docs/005 is actually after ("an incident's full history is
reconstructable from the event log alone") without a separate async
pub/sub dispatch loop. Preemption is enforced between stages (matching
the state diagram, which only branches to Preempted at state boundaries),
not by aborting an agent mid-call. See orchestrate/README.md.
"""

from typing import Tuple

from agents import (
    CADSpecAgent,
    CausalIsolationAgent,
    FeedbackCalibrationAgent,
    ImpactSimulationAgent,
    ParameterAdjustmentAgent,
    ReroutingAgent,
    SubstitutionAgent,
    VisionSpecAgent,
)
from agents.sdk import IncidentContext, StageInput, StageOutput
from contracts import EventEnvelope
from knowledge import CausalGraph, DigitalTwinStore, KnowledgeGraph

from backend.app.eventbus import EventBus


class AgentRunner:
    def __init__(
        self,
        event_bus: EventBus,
        knowledge_graph: KnowledgeGraph,
        causal_graph: CausalGraph,
        digital_twin: DigitalTwinStore,
    ):
        self._bus = event_bus
        self._kg = knowledge_graph
        self._cg = causal_graph
        self._dt = digital_twin
        self._agents = {
            "vision_spec": VisionSpecAgent(knowledge_graph=self._kg),
            "cad_spec": CADSpecAgent(knowledge_graph=self._kg),
            "causal_isolation": CausalIsolationAgent(
                causal_graph=self._cg, knowledge_graph=self._kg
            ),
            "substitution": SubstitutionAgent(knowledge_graph=self._kg),
            "parameter_adjustment": ParameterAdjustmentAgent(digital_twin=self._dt),
            "impact_simulation": ImpactSimulationAgent(),
            "rerouting": ReroutingAgent(digital_twin=self._dt),
            "feedback_calibration": FeedbackCalibrationAgent(causal_graph=self._cg),
        }

    async def run_stage(
        self, agent_key: str, context: IncidentContext, stage_input: StageInput
    ) -> Tuple[StageOutput, EventEnvelope]:
        agent = self._agents[agent_key]

        requested = EventEnvelope(
            event_type="StageRequested",
            incident_id=context.incident_id,
            produced_by="orchestrate/decision-orchestrator",
            payload={"agentId": agent.agent_id, "stageName": stage_input.stage_name},
        )
        await self._bus.publish(requested)

        output, envelope = agent.run(context, stage_input)
        await self._bus.publish(envelope)
        return output, envelope
