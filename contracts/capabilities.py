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

    # HR domain pod (orchestrate/moa/hr_domain.py) — MOA vertical-slice
    # milestone, orchestration-platform-vision.md §11 build-sequence step 2.
    REVOKE_BUILDING_ACCESS = "RevokeBuildingAccess"
    DISABLE_IT_ACCESS = "DisableITAccess"
    STOP_PAYROLL = "StopPayroll"
    NOTIFY_MANAGER = "NotifyManager"

    # IT domain pod (orchestrate/moa/it_domain.py)
    NOTIFY_IT_HELPDESK = "NotifyITHelpdesk"
    GRANT_JIRA_ACCESS = "GrantJiraAccess"
    REVOKE_AWS_ROLE = "RevokeAWSRole"
    DEPROVISION_CLOUD_ACCOUNT = "DeprovisionCloudAccount"

    # Finance domain pod (orchestrate/moa/finance_domain.py)
    FLAG_INVOICE_DISCREPANCY = "FlagInvoiceDiscrepancy"
    APPROVE_EXPENSE_REIMBURSEMENT = "ApproveExpenseReimbursement"
    ISSUE_VENDOR_PAYMENT_HOLD = "IssueVendorPaymentHold"
    PROCESS_WIRE_TRANSFER = "ProcessWireTransfer"

    # Manufacturing domain pod (orchestrate/moa/manufacturing_domain.py)
    REROUTE_STATION = "RerouteStation"
    EVALUATE_GNN_RISK = "EvaluateGNNRisk"
    READ_RUL_TELEMETRY = "ReadRULTelemetry"
    SORT_WORKPIECE = "SortWorkpiece"

    # Self-Learning RLM Agent (Prime Intellect prime-agent harness)
    RUN_PRIME_RLM_AGENT = "RunPrimeRLMAgent"

    # Mission evidence retrieval (integrations/connectors/mission_evidence.py).
    # Reads ADOS's own record of a mission and has no side effect.
    #
    # It exists because evidence must be RETRIEVED through the governed path,
    # not handed to the runtime for free. A runtime pre-loaded with its evidence
    # can still produce a report when its tools are broken — and one did,
    # inventing a disk-space root cause it had no way to have observed. Make the
    # facts reachable only through a capability, and a broken runtime produces
    # no facts, which ADOS can see.
    FETCH_INCIDENT_EVIDENCE = "FetchIncidentEvidence"

    # Capability Onboarding (orchestrate/onboarding/, §8) — one sentinel for
    # every dynamically onboarded capability. CapabilityCall.capability stays
    # a closed, Pydantic-enforced enum; the real free-text capability_id
    # (e.g. "zendesk.read_ticket", tracked by CapabilityManifestRegistry)
    # rides in CapabilityCall.input["capability_id"] instead. See
    # integrations/connectors/dynamic.py for the dispatch side of this.
    DYNAMIC_CAPABILITY = "DynamicCapability"



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
