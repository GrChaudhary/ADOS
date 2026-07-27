"""
Capability catalog and governance enums per docs/006-integration-hub.md
and docs/007-governance.md. Kept separate from event_envelope.py /
agent_events.py (owned by the agents/knowledge Phase 2 work) since this is
the Integration Hub side of the contract (Phase 1).
"""

from enum import Enum


class Capability(str, Enum):
    """Abstract capabilities exposed by the Integration Hub's Capability
    Registry — see docs/006-integration-hub.md. Orchestration/agent code
    depends only on these names, never on a connector's vendor API."""

    CREATE_PURCHASE_ORDER = "CreatePurchaseOrder"
    CREATE_INCIDENT = "CreateIncident"
    RESERVE_INVENTORY = "ReserveInventory"
    NOTIFY_OPERATOR = "NotifyOperator"
    UPDATE_MES = "UpdateMES"
    CREATE_CHANGE_REQUEST = "CreateChangeRequest"
    SCHEDULE_MAINTENANCE = "ScheduleMaintenance"
    QUERY_EXTERNAL_STOCK = "QueryExternalStock"
    CREATE_EXTERNAL_PO = "CreateExternalPO"
    GET_FREIGHT_QUOTE = "GetFreightQuote"
    QUERY_DATABASE = "QueryDatabase"
    PERSIST_INCIDENT = "PersistIncident"


class PolicyTier(int, Enum):
    """Governance policy tiers — docs/007-governance.md."""

    AUTONOMOUS = 0
    APPROVAL_REQUIRED = 1
    EXECUTIVE_APPROVAL = 2


class CallStatus(str, Enum):
    """Capability call outcome — docs/010-api-contracts.md."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
