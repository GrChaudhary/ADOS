"use client";

export default function IntegrationsPage() {
  const connectors = [
    {
      id: "watsonx_itsm",
      name: "IBM watsonx Orchestrate ITSM",
      status: "Connected 🟢",
      auth: "IBM Cloud IAM OAuth 2.0",
      module: "integrations/connectors/watsonx_itsm.py",
      description: "Automated IT/OT incident creation, change request logging, and operator notifications.",
      capabilities: ["CreateIncident", "CreateChangeRequest", "ScheduleMaintenance", "NotifyOperator"],
    },
    {
      id: "sap_erp",
      name: "SAP S/4HANA ERP Connector",
      status: "Connected 🟢",
      auth: "SAP BAPI / OData REST API",
      module: "integrations/connectors/sap.py",
      description: "Automated B2B purchase order dispatch, component soft reservations, and ERP inventory updates.",
      capabilities: ["CreatePurchaseOrder", "ReserveInventory", "QueryStockBalance"],
    },
    {
      id: "b2b_marketplace",
      name: "External B2B Marketplace Connector",
      status: "Connected 🟢",
      auth: "REST API + Bearer Secret Token",
      module: "integrations/connectors/marketplace.py",
      description: "Real-time query of global tier-1/tier-2 supplier inventory, stock lead times, and freight quotes.",
      capabilities: ["QueryExternalStock", "CreateExternalPO", "GetFreightQuote"],
    },
    {
      id: "factory_mes",
      name: "Factory MES & PLC Digital Twin",
      status: "Connected 🟢",
      auth: "OPC-UA / Modbus TCP Protocol",
      module: "knowledge/digital_twin.py",
      description: "Direct machine spindle parameter tuning, telemetry streaming, and preemption locks.",
      capabilities: ["UpdateMachineFeed", "ApplySoftLock", "StreamTelemetry"],
    },
  ];

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Enterprise Integration Monitor</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald/10 text-emerald border border-emerald/30">
              Layer 4 Integration Hub
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Enterprise system connectors, authentication status, API payload contracts, and dispatch logs.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono">
          <div className="px-3 py-1.5 rounded-lg bg-dark-900/60 border border-border-subtle text-text-secondary">
            Connectors Active: <span className="text-emerald font-bold">4 / 4</span>
          </div>
        </div>
      </div>

      {/* 4 Connected System Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {connectors.map((c) => (
          <div
            key={c.id}
            className="p-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle hover:border-border-accent transition-all space-y-4 shadow-lg"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-xl">🔌</span>
                <h2 className="text-base font-semibold text-text-primary">{c.name}</h2>
              </div>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald/20 text-emerald border border-emerald/40 font-semibold">
                {c.status}
              </span>
            </div>

            <p className="text-xs text-text-secondary">{c.description}</p>

            <div className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle space-y-2 text-xs font-mono">
              <div className="flex justify-between">
                <span className="text-text-secondary">Auth Protocol:</span>
                <span className="text-cobalt font-medium">{c.auth}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-secondary">Module Source:</span>
                <span className="text-mono text-text-primary">{c.module}</span>
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="text-xs font-mono text-text-secondary">Exposed Capabilities:</div>
              <div className="flex flex-wrap gap-1.5">
                {c.capabilities.map((cap) => (
                  <span key={cap} className="px-2 py-1 rounded text-[11px] font-mono bg-cobalt/10 text-cobalt border border-cobalt/20">
                    {cap}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Integration Bus Specifications */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚙️</span>
            <h2 className="text-lg font-semibold text-text-primary">Integration Bus &amp; Routing Specs</h2>
          </div>
          <span className="text-xs font-mono text-cobalt px-2.5 py-1 rounded bg-cobalt/10 border border-cobalt/20">
            Event Bus Alias Routing Active
          </span>
        </div>

        <div className="space-y-2 text-xs font-mono text-text-secondary">
          <p>
            All backend integration services are exposed under both unprefixed and <code className="text-emerald">/api/v1/...</code> alias routes with CORS support for <code className="text-cobalt">http://localhost:3000</code>.
          </p>
          <div className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle space-y-1">
            <div className="text-text-primary">Primary Authorization Header: <code className="text-cobalt">Authorization: Bearer dev-local-only-token</code></div>
            <div className="text-text-primary">SSE Event Bus Endpoint: <code className="text-emerald">GET /api/v1/events/stream?token=...</code></div>
          </div>
        </div>
      </div>
    </div>
  );
}
