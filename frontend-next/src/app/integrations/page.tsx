"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, Capability, getStoredUser, IntegrationConnectorItem, PolicyTier } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

// The 4 capabilities integrations/connectors/watsonx_itsm.py actually
// fulfills - see its _ITSM_CAPABILITIES set. Only ScheduleMaintenance is
// ever reached through the normal incident pipeline
// (orchestrate/orchestrator.py's _capability_for_option); this form is the
// only way to exercise the other three at all.
const ITSM_CAPABILITIES: Capability[] = [
  "CreateIncident",
  "CreateChangeRequest",
  "ScheduleMaintenance",
  "NotifyOperator",
];

const IMPACT_URGENCY_OPTIONS = ["1 - High", "2 - Medium", "3 - Low"];

function ManualTicketForm() {
  const user = getStoredUser();
  const [capability, setCapability] = useState<Capability>("CreateIncident");
  const [shortDescription, setShortDescription] = useState("");
  const [description, setDescription] = useState("");
  const [impact, setImpact] = useState("2 - Medium");
  const [urgency, setUrgency] = useState("2 - Medium");
  const [policyTier, setPolicyTier] = useState<PolicyTier>(0);

  const invokeMutation = useMutation({
    mutationFn: api.invokeCapability,
  });

  function submit() {
    if (!shortDescription.trim()) return;
    const confirmed = window.confirm(
      `This creates a REAL ServiceNow record via ${capability} — not a simulation. Continue?`
    );
    if (!confirmed) return;

    invokeMutation.mutate({
      capability,
      incidentId: `manual-${Date.now()}`,
      requestedBy: user?.displayName ?? "manual-ui",
      input: { short_description: shortDescription, description, impact, urgency },
      governance: { policyTier, approvedBy: user?.displayName ?? "manual-ui" },
    });
  }

  return (
    <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">🎫</span>
          <h2 className="text-lg font-semibold text-text-primary">Manually Create Ticket</h2>
        </div>
        <span className="text-xs font-mono text-status-red px-2.5 py-1 rounded bg-status-red/10 border border-status-red/20">
          Creates a real ServiceNow record — bypasses the incident pipeline
        </span>
      </div>

      <p className="text-xs text-text-secondary">
        Calls <code className="text-cobalt">POST /capabilities/invoke</code> directly — no vision/causal/
        governance stages run. You&apos;re providing the governance decision yourself below.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="text-xs font-mono text-text-secondary">Capability</label>
          <select
            value={capability}
            onChange={(e) => setCapability(e.target.value as Capability)}
            className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary"
          >
            {ITSM_CAPABILITIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-mono text-text-secondary">Governance Tier</label>
          <select
            value={policyTier}
            onChange={(e) => setPolicyTier(Number(e.target.value) as PolicyTier)}
            className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary"
          >
            <option value={0}>Tier 0 — Autonomous</option>
            <option value={1}>Tier 1 — Engineer Approval</option>
            <option value={2}>Tier 2 — Executive Approval</option>
          </select>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs font-mono text-text-secondary">Short Description *</label>
        <input
          type="text"
          value={shortDescription}
          onChange={(e) => setShortDescription(e.target.value)}
          placeholder="e.g. Line 2 CNC-102 spindle vibration exceeding threshold"
          className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/50"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs font-mono text-text-secondary">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="Full details for the ticket..."
          className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/50 resize-none"
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="text-xs font-mono text-text-secondary">Impact</label>
          <select
            value={impact}
            onChange={(e) => setImpact(e.target.value)}
            className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary"
          >
            {IMPACT_URGENCY_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-mono text-text-secondary">Urgency</label>
          <select
            value={urgency}
            onChange={(e) => setUrgency(e.target.value)}
            className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary"
          >
            {IMPACT_URGENCY_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      </div>

      <div className="flex items-center justify-between pt-2">
        <button
          onClick={submit}
          disabled={!shortDescription.trim() || invokeMutation.isPending}
          className="rounded-md bg-status-red px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {invokeMutation.isPending ? "Creating…" : "Create Real Ticket"}
        </button>
      </div>

      {invokeMutation.data && (
        <div
          className={`p-3 rounded-lg border text-xs font-mono ${
            invokeMutation.data.status === "succeeded"
              ? "bg-emerald/10 border-emerald/30 text-emerald"
              : "bg-status-red/10 border-status-red/30 text-status-red"
          }`}
        >
          {invokeMutation.data.status === "succeeded" ? (
            <>🟢 Created via {invokeMutation.data.connector} — ticket: {String(invokeMutation.data.output.ticket_id ?? "(no id returned)")}</>
          ) : (
            <>🔴 Failed via {invokeMutation.data.connector ?? "no connector selected"}: {invokeMutation.data.error}</>
          )}
        </div>
      )}
      {invokeMutation.isError && (
        <div className="p-3 rounded-lg border text-xs font-mono bg-status-red/10 border-status-red/30 text-status-red">
          {String(invokeMutation.error)}
        </div>
      )}
    </div>
  );
}

function badgeClass(c: IntegrationConnectorItem): string {
  // Checked before `connected` - marketplace.py's execute() never makes a
  // real HTTP call, so it reports connected=true (it "responds") even
  // though it isn't reaching a real system. Simulated must never render
  // with the same green as a genuinely live connection like Cloudant's.
  if (/simulated/i.test(c.status)) return "bg-amber/20 text-amber border-amber/40";
  if (c.connected) return "bg-emerald/20 text-emerald border-emerald/40";
  return "bg-status-red/20 text-status-red border-status-red/40";
}

export default function IntegrationsPage() {
  const hasToken = useHasToken();

  const statusQuery = useQuery<IntegrationConnectorItem[]>({
    queryKey: ["integrations-status"],
    queryFn: api.getIntegrationsStatus,
    refetchInterval: 5000,
    enabled: hasToken,
  });

  const watsonxTest = useMutation({
    mutationFn: api.testWatsonxConnection,
  });

  const connectors = statusQuery.data ?? [];
  const connectedCount = connectors.filter((c) => c.connected).length;

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
            Real-time enterprise connectors, live Cloudant NoSQL document stores, ping latency metrics, and capability contracts.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono">
          <div className="px-3 py-1.5 rounded-lg bg-glass border border-border-subtle text-text-secondary">
            Connectors Active:{" "}
            <span className="text-emerald font-bold">
              {hasToken && statusQuery.data ? `${connectedCount} / ${connectors.length}` : "—"}
            </span>
          </div>
        </div>
      </div>

      {!hasToken && (
        <p className="text-sm text-status-red">Enter a service token above to load connector status.</p>
      )}
      {hasToken && statusQuery.isLoading && (
        <p className="text-sm text-text-secondary">Polling live connector health &amp; Cloudant status...</p>
      )}
      {hasToken && statusQuery.isError && (
        <p className="text-sm text-status-red">Could not load connector status (check backend &amp; service token).</p>
      )}

      {/* Connector Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {connectors.map((c) => {
          const isCloudant = c.id === "cloudant_nosql";
          return (
            <div
              key={c.id}
              className={`p-6 rounded-xl bg-card/60 backdrop-blur-md border ${
                isCloudant ? "border-emerald/40 shadow-emerald/5 shadow-xl" : "border-border-subtle hover:border-border-accent"
              } transition-all space-y-4 shadow-lg`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">{isCloudant ? "☁️" : "🔌"}</span>
                  <h2 className="text-base font-semibold text-text-primary">{c.name}</h2>
                </div>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono border font-semibold ${badgeClass(c)}`}>
                  {c.status}
                </span>
              </div>

              <p className="text-xs text-text-secondary">{c.description}</p>

              <div className="p-3 rounded-lg bg-glass border border-border-subtle space-y-2 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-text-secondary">Auth Protocol:</span>
                  <span className="text-cobalt font-medium">{c.auth}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Module Source:</span>
                  <span className="text-mono text-text-primary">{c.module}</span>
                </div>
                {c.latency_ms != null && (
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Ping Latency:</span>
                    <span className="text-emerald font-bold">{c.latency_ms} ms</span>
                  </div>
                )}
                {c.doc_count != null && (
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Live Cloudant Doc Count:</span>
                    <span className="text-purple font-bold">{c.doc_count} Documents</span>
                  </div>
                )}
                {c.host && (
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Host Instance:</span>
                    <span className="text-xs text-text-primary truncate max-w-[200px]">{c.host}</span>
                  </div>
                )}
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

              {c.id === "watsonx_itsm" && (
                <div className="pt-2 border-t border-border-subtle space-y-2">
                  <button
                    onClick={() => watsonxTest.mutate()}
                    disabled={!hasToken || watsonxTest.isPending}
                    className="px-3 py-1.5 rounded-lg text-xs font-mono bg-cobalt/10 text-cobalt border border-cobalt/30 hover:bg-cobalt/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {watsonxTest.isPending ? "Testing…" : "Test Live Connection"}
                  </button>
                  {watsonxTest.data && (
                    <div
                      className={`p-2.5 rounded-lg border text-xs font-mono ${
                        watsonxTest.data.connected
                          ? "bg-emerald/10 border-emerald/30 text-emerald"
                          : "bg-status-red/10 border-status-red/30 text-status-red"
                      }`}
                    >
                      {watsonxTest.data.connected ? (
                        <>
                          🟢 Live — {watsonxTest.data.agentCount} agent(s) registered
                          {watsonxTest.data.agents && watsonxTest.data.agents.length > 0 && (
                            <>: {watsonxTest.data.agents.join(", ")}</>
                          )}
                        </>
                      ) : (
                        <>🔴 {watsonxTest.data.error}</>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Manual Ticket Creation */}
      {hasToken && <ManualTicketForm />}

      {/* Integration Bus Specifications */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚙️</span>
            <h2 className="text-lg font-semibold text-text-primary">Integration Bus &amp; Routing Specs</h2>
          </div>
          <span className="text-xs font-mono text-cobalt px-2.5 py-1 rounded bg-cobalt/10 border border-cobalt/20">
            Cloudant NoSQL Event Bus Active
          </span>
        </div>

        <div className="space-y-2 text-xs font-mono text-text-secondary">
          <p>
            All backend integration services are exposed under both unprefixed and <code className="text-emerald">/api/v1/...</code> alias routes with CORS support for <code className="text-cobalt">http://localhost:3000</code>.
          </p>
          <div className="p-3 rounded-lg bg-glass border border-border-subtle space-y-1">
            <div className="text-text-primary">Cloudant Database: <code className="text-purple">ados_incidents</code> &amp; <code className="text-purple">ados_events</code></div>
            <div className="text-text-primary">Primary Authorization Header: <code className="text-cobalt">Authorization: Bearer dev-local-only-token</code></div>
            <div className="text-text-primary">SSE Event Bus Endpoint: <code className="text-emerald">GET /api/v1/events/stream?token=...</code></div>
          </div>
        </div>
      </div>
    </div>
  );
}
