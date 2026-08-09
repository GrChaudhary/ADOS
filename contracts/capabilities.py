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
    """Capability call outcome — docs/010-api-contracts.md.

    A capability call passes through six distinct stages, and ADOS must never
    collapse them:

        1. request accepted        the gateway parsed and admitted the request
        2. capability authorized   the mission's grant permits it
        3. connector invoked       a connector was selected and called
        4. remote system acked     the far side returned a response we read
        5. execution confirmed     the action actually happened out there
        6. mission success         the confirmed action satisfied the mission

    **A connector returning normally proves stage 3, not stage 5.** The absence
    of an exception is a statement about our process, not about the world. Every
    expensive bug in this system has come from treating one as the other: a
    blank ServiceNow ticket recorded as SUCCEEDED, a factory connector reporting
    a completed reroute while the gateway was unplugged, an agent's fabricated
    root-cause report accepted as analysis.

    SUCCEEDED therefore means stage 5 — confirmed. Nothing weaker earns it.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

    # The honest third outcome, for actions whose effect ADOS cannot observe.
    #
    # ADOS sends a command to the factory; the connection drops before a reply
    # arrives. The workpiece may have been re-dispatched or may not have been.
    # SUCCEEDED is a lie. FAILED is also a lie, and the more dangerous one — it
    # invites a retry that could execute a physical action twice.
    #
    # Reserved for EXTERNAL, side-effecting calls where the request was already
    # in flight when contact was lost. A call that never left (DNS failure,
    # connection refused) is plainly FAILED: nothing happened, retry is safe.
    # The distinction is whether the far side could have acted, and it decides
    # whether a retry is safe — which is why it must survive into the audit
    # record rather than being rounded to the nearest binary.
    #
    # Terminal for the call, NOT for the question. An UNKNOWN row is a debt:
    # something must later reconcile it against the remote system's own state.
    UNKNOWN = "unknown"


#: Statuses that assert the action really happened. Deliberately a set of one.
#: Written as a named constant so "did this succeed?" is a single expression
#: that reads the same everywhere, and so any future addition has to be a
#: conscious edit here rather than a `!= FAILED` scattered through call sites.
CONFIRMED_STATUSES = frozenset({CallStatus.SUCCEEDED})

#: Statuses where the real-world effect is genuinely undetermined. These must
#: never be retried automatically and must never be reported as done.
UNRESOLVED_STATUSES = frozenset({CallStatus.UNKNOWN})
