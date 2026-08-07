from .base import Connector
from .console import ConsoleConnector
from .sap import SAPConnector
from .servicenow import ServiceNowConnector
from .marketplace import MarketplaceConnector

__all__ = ["Connector", "ConsoleConnector", "ServiceNowConnector", "SAPConnector", "MarketplaceConnector"]

# DynamicCapabilityConnector is deliberately not re-exported here: it
# imports from integrations.capability_manifest, which is upstream of this
# package in the import chain (capability_manifest -> policy_engine ->
# capability_registry -> connectors/__init__.py) — eagerly importing it at
# package-init time creates a circular import. Import it directly instead:
# `from integrations.connectors.dynamic import DynamicCapabilityConnector`
# (same convention hub.py already uses for every other connector).
