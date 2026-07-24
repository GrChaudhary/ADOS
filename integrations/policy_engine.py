"""
Connector Policy Engine — docs/006-integration-hub.md. Resolves a
capability call to a specific connector and validates it against
governance rules before execution: budget thresholds, regional
restrictions, compliance, approval routing, preferred systems, least
privilege. The MVP implements the resolution/rejection mechanics with a
pass-through rule set — real rules get added here as policy data grows,
without orchestration/agent code changing (docs/009-security.md).
"""

from typing import Callable, List

from contracts import CapabilityCall

from .capability_registry import CapabilityRegistry
from .connectors.base import Connector


class PolicyViolation(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


PolicyRule = Callable[[CapabilityCall], None]  # raises PolicyViolation to deny


def require_governance(call: CapabilityCall) -> None:
    if call.governance is None:
        raise PolicyViolation("capability call missing required governance context")


class ConnectorPolicyEngine:
    def __init__(self, registry: CapabilityRegistry, rules: List[PolicyRule] = None):
        self._registry = registry
        self._rules = rules if rules is not None else [require_governance]

    def select_connector(self, call: CapabilityCall) -> Connector:
        for rule in self._rules:
            rule(call)  # raises PolicyViolation to deny

        candidates = self._registry.connectors_for(call.capability)
        if not candidates:
            raise PolicyViolation(
                f"no connector registered for capability {call.capability.value}"
            )
        # "Preferred systems": prefer a configured real connector (e.g.
        # ServiceNow/SAP with credentials set) over an unconfigured one,
        # in registration order; fall back to the first candidate
        # (typically console) if nothing is configured yet. Budget/
        # regional/compliance ranking would extend this same list, not
        # replace it.
        configured = [c for c in candidates if c.is_configured()]
        return configured[0] if configured else candidates[0]
