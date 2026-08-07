"""
Base Agent abstract class and SDK foundation for ADOS reasoning agents.
"""

import time
import abc
from typing import Tuple, List, Optional
from contracts import EventEnvelope, AgentCompletedPayload
from .models import IncidentContext, StageInput, StageOutput, EvidenceItem, AlternativeOption


class BaseAgent(abc.ABC):
    """
    Abstract base agent conforming to docs/004-agent-framework.md.
    Every agent accepts IncidentContext + StageInput and returns StageOutput.
    """

    def __init__(self, agent_id: str, stage_name: str):
        self.agent_id = agent_id
        self.stage_name = stage_name

    @abc.abstractmethod
    def process(self, context: IncidentContext, stage_input: StageInput) -> StageOutput:
        """Core reasoning logic implemented by individual specialist agents."""
        pass

    def run(self, context: IncidentContext, stage_input: StageInput) -> Tuple[StageOutput, EventEnvelope]:
        """
        Executes the agent, measures latency, constructs StageOutput,
        and produces the canonical AgentCompleted EventEnvelope.
        """
        start_time = time.time()
        output = self.process(context, stage_input)
        execution_time_ms = round((time.time() - start_time) * 1000, 2)

        # Build completion payload
        payload = AgentCompletedPayload(
            agent_id=self.agent_id,
            stage_name=self.stage_name,
            execution_time_ms=execution_time_ms,
            confidence=output.confidence,
            result=output.result,
            evidence=[e.model_dump(by_alias=True) for e in output.evidence],
            alternatives=[a.model_dump(by_alias=True) for a in output.alternatives]
        )

        # Wrap in standard event envelope
        envelope = EventEnvelope(
            event_type="AgentCompleted",
            correlation_id=context.incident_id,
            produced_by=f"agents/{self.agent_id}",
            schema_version="1.0.0",
            payload=payload.model_dump(by_alias=True)
        )

        return output, envelope
