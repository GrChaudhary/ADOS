"""
Integration Hub facade — wires the Capability Registry, Connector Policy
Engine, and connectors together for callers (the backend API for now;
the Decision Orchestrator in Phase 3). See docs/006-integration-hub.md's
example resolution:

    Need -> Capability Registry -> Connector Policy Engine -> Connector -> Execute
"""

from contracts import CallStatus, CapabilityCall, CapabilityResponse

from .capability_registry import CapabilityRegistry
from .connectors.console import ConsoleConnector
from .connectors.sap import SAPConnector
from .connectors.servicenow import ServiceNowConnector
from .connectors.watsonx_itsm import WatsonxITSMConnector
from .connectors.marketplace import MarketplaceConnector
from .policy_engine import ConnectorPolicyEngine, PolicyViolation


class IntegrationHub:
    def __init__(self):
        self.registry = CapabilityRegistry()
        self.policy_engine = ConnectorPolicyEngine(self.registry)

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


def default_hub() -> IntegrationHub:
    """Real connectors registered first so the Connector Policy Engine's
    "preferred systems" rule (docs/006-integration-hub.md) picks them once
    configured; Console registered last as the universal fallback for
    everything else (NotifyOperator, UpdateMES) and for capabilities whose
    real connector isn't configured yet. WatsonxITSMConnector requires
    WO_ITSM_INTEGRATION_ENABLED=true in addition to WO_INSTANCE/WO_API_KEY
    — see its is_configured() docstring for why those aren't sufficient
    alone."""
    hub = IntegrationHub()
    hub.registry.register(WatsonxITSMConnector())
    hub.registry.register(MarketplaceConnector())
    hub.registry.register(ServiceNowConnector())
    hub.registry.register(SAPConnector())
    hub.registry.register(ConsoleConnector())
    return hub
