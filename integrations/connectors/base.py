"""
Connector base class — docs/006-integration-hub.md. A connector fulfills
one or more capabilities against a real (or, for the MVP, simulated)
enterprise system. Orchestration/agent code never talks to a connector
directly; it goes through the Capability Registry + Connector Policy
Engine.
"""

import abc
from typing import Dict, Set

from contracts import Capability, CapabilityCall, CapabilityResponse


class Connector(abc.ABC):
    name: str
    capabilities: Set[Capability]

    @abc.abstractmethod
    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        """Fulfill a capability call. Implementations should catch their
        own vendor-specific errors and return a CapabilityResponse with
        status=FAILED rather than raising, so the orchestrator's
        retry/rollback (docs/005-decision-orchestrator.md) has a uniform
        response shape to react to."""

    def is_configured(self) -> bool:
        """Whether this connector has the credentials/config it needs to
        actually reach its vendor system. Default True (the console
        connector needs none); real connectors override this so the
        Connector Policy Engine's "preferred systems" rule
        (docs/006-integration-hub.md) can prefer a configured real
        connector but still fall back to console when one isn't set up
        yet, rather than failing every call."""
        return True
