"""
Integration Hub facade — wires the Capability Registry, Connector Policy
Engine, and connectors together for callers (the backend API for now;
the Decision Orchestrator in Phase 3). See docs/006-integration-hub.md's
example resolution:

    Need -> Capability Registry -> Connector Policy Engine -> Connector -> Execute
"""

from typing import Optional

from contracts import CallStatus, CapabilityCall, CapabilityResponse

from .capability_manifest import CapabilityManifestRegistry, hot_disable_policy_rule
from .capability_registry import CapabilityRegistry
from .connectors.console import ConsoleConnector
from .connectors.dynamic import DynamicCapabilityConnector
from .connectors.sap import SAPConnector
from .connectors.servicenow import ServiceNowConnector
from .connectors.marketplace import MarketplaceConnector
from .policy_engine import ConnectorPolicyEngine, PolicyViolation, require_governance


class IntegrationHub:
    def __init__(self, manifests: Optional[CapabilityManifestRegistry] = None):
        self.registry = CapabilityRegistry()
        # manifests defaults to a fresh, empty registry rather than None so
        # this is always wired in — see hot_disable_policy_rule's docstring
        # for why an empty registry is a safe no-op today (nothing has been
        # onboarded through §8 yet) and starts enforcing the moment
        # something calls self.manifests.propose(...).
        self.manifests = manifests if manifests is not None else CapabilityManifestRegistry()
        # Always constructed (mirrors self.manifests) so callers/tests always
        # have a handle to attach track executors (register_executor) or
        # dispatch configs to — but, like every other connector, it's only
        # *registered* (made reachable by hub.invoke()) where a hub
        # explicitly opts in, i.e. default_hub() below.
        self.dynamic_capability_connector = DynamicCapabilityConnector(self.manifests)
        self.policy_engine = ConnectorPolicyEngine(
            self.registry, rules=[require_governance, hot_disable_policy_rule(self.manifests)]
        )

    async def invoke(self, call: CapabilityCall) -> CapabilityResponse:
        try:
            connector = self.policy_engine.select_connector(call)
        except PolicyViolation as e:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                error=str(e),
            )
        return await connector.execute(call)


def default_hub(manifests: Optional[CapabilityManifestRegistry] = None) -> IntegrationHub:
    """Real connectors registered first so the Connector Policy Engine's
    "preferred systems" rule (docs/006-integration-hub.md) picks them once
    configured; Console registered last as the universal fallback for
    everything else (NotifyOperator, UpdateMES) and for capabilities whose
    real connector isn't configured yet.

    `manifests` lets the real app (backend/app/main.py) pass a
    Postgres-backed CapabilityManifestRegistry instead of the default
    empty in-memory one — see integrations/capability_manifest.py's
    session_factory docstring.

    dynamic_capability_connector is registered before ConsoleConnector for
    the same "preferred systems" reason: ConsoleConnector's
    capabilities = set(Capability) covers Capability.DYNAMIC_CAPABILITY too
    (it's re-evaluated fresh, so it picks up the sentinel automatically),
    and both connectors report is_configured() = True by default — without
    this ordering, ConsoleConnector would silently win and no dynamically
    onboarded capability would ever actually execute."""
    hub = IntegrationHub(manifests=manifests)
    hub.registry.register(MarketplaceConnector())
    hub.registry.register(ServiceNowConnector())
    hub.registry.register(SAPConnector())
    hub.registry.register(hub.dynamic_capability_connector)
    hub.registry.register(ConsoleConnector())
    return hub
