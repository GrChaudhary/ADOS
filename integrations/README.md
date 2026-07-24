# integrations/

The Integration Hub: Capability Registry, Connector Manager, Connector
Policy Engine, Secrets Manager, API Gateway, and the individual connector
implementations (SAP, Oracle ERP, ServiceNow, Jira Service Management, IBM
Maximo, Teams, Slack, MQTT, Kafka, OPC-UA, REST, GraphQL).

New enterprise system support is added here as a new connector
implementing an existing capability — orchestration and agent code should
never need to change for a new connector.

Relevant chapters: [006-integration-hub](../docs/006-integration-hub.md)
(the design this module implements), [009-security](../docs/009-security.md)
(Secrets Manager, least privilege), [010-api-contracts](../docs/010-api-contracts.md)
(capability call contract).

Roadmap: Phase 1 (Integration Hub scaffold), Phase 3 (ServiceNow, SAP
connectors).

## Status: Phase 3A — real connectors added

```
capability_registry.py   Capability -> [Connector] mapping
policy_engine.py         ConnectorPolicyEngine — governance check + "prefer
                          configured real connector, else fall back" selection
hub.py                   IntegrationHub facade; default_hub() registers
                          watsonx ITSM, ServiceNow, SAP, then console (fallback)
connectors/
  base.py                Connector abstract base + is_configured()
  console.py             ConsoleConnector — logs + succeeds for every
                          capability; the universal fallback
  servicenow.py           real Table API integration (CreateIncident,
                          CreateChangeRequest, ScheduleMaintenance)
  sap.py                  real OData integration, CSRF-token-then-POST
                          (CreatePurchaseOrder, ReserveInventory)
  watsonx_itsm.py          IBM IAM token exchange + Orchestrate agent
                          endpoint (CreateIncident, CreateChangeRequest,
                          ScheduleMaintenance, NotifyOperator) — requires
                          WO_ITSM_INTEGRATION_ENABLED=true, deliberately
                          separate from WO_INSTANCE/WO_API_KEY (the ADK
                          CLI's own auth) since the REST endpoint it calls
                          isn't verified against a live instance yet
```

Wired into `backend/`'s `POST /capabilities/invoke` and
`orchestrate/`'s `DecisionOrchestrator`. Every `CapabilityCall` must
carry `governance` (policy tier + approver) or the Policy Engine rejects
it before a connector ever runs — see `require_governance` in
`policy_engine.py` and [007-governance](../docs/007-governance.md).

**ServiceNow and SAP are untested against real instances** — no sandbox
was available for this pass. Both fail clearly ("not configured") rather
than pretending to succeed when `SERVICENOW_*`/`SAP_*` env vars
(`../.env.example`) are unset, in which case the Policy Engine falls back
to the console connector automatically. Request shape (auth headers,
table/service paths, SAP's CSRF flow) is verified against
`httpx.MockTransport` in `../tests/test_connectors.py` — real-instance
verification is a follow-up once credentials exist.

Adding a real connector: implement `Connector` in `connectors/`, register
it in `hub.default_hub()` before `ConsoleConnector` — `backend/`'s router
and `orchestrate/`'s calls-by-capability-name don't change.
