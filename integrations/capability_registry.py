"""
Capability Registry — docs/006-integration-hub.md. Maps each abstract
Capability to the connector(s) that can fulfill it. Orchestration/agent
code depends only on Capability names (contracts/capabilities.py), never
on this mapping directly — it goes through the Connector Policy Engine.
"""

from typing import Dict, List

from contracts import Capability

from .connectors.base import Connector


class CapabilityRegistry:
    def __init__(self):
        self._connectors_by_capability: Dict[Capability, List[Connector]] = {}

    def register(self, connector: Connector) -> None:
        for capability in connector.capabilities:
            self._connectors_by_capability.setdefault(capability, []).append(connector)

    def connectors_for(self, capability: Capability) -> List[Connector]:
        return self._connectors_by_capability.get(capability, [])

    def is_supported(self, capability: Capability) -> bool:
        return bool(self._connectors_by_capability.get(capability))

    def list_connectors(self) -> List[Connector]:
        """Every registered connector, deduped by identity (a connector can
        be registered under several capabilities)."""
        seen: Dict[str, Connector] = {}
        for connectors in self._connectors_by_capability.values():
            for connector in connectors:
                seen[connector.name] = connector
        return list(seen.values())
