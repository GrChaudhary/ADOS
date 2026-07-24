"""
Guards the one thing that makes running Phase 1 (backend/integrations) and
Phase 2 (agents/knowledge) in parallel safe: an EventEnvelope produced by
an agent must be publishable/readable through the backend's actual event
bus, not just structurally equal to it. If this breaks, contracts/ has
diverged between the two workstreams.
"""

import pytest

from agents.sdk.models import IncidentContext, StageInput
from agents.vision_spec_agent import VisionSpecAgent
from backend.app.eventbus import InMemoryEventBus


@pytest.mark.asyncio
async def test_agent_event_round_trips_through_backend_event_bus():
    agent = VisionSpecAgent()
    context = IncidentContext(plant_id="FAC-P1", line_id="Line3")
    stage_input = StageInput(stage_name="perception", payload={})

    output, envelope = agent.run(context, stage_input)

    bus = InMemoryEventBus()
    await bus.publish(envelope)

    recent = await bus.recent(incident_id=context.incident_id)
    assert len(recent) == 1
    assert recent[0].event_type == "AgentCompleted"
    assert recent[0].payload["confidence"] == pytest.approx(output.confidence)
