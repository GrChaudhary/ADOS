"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, Capability, CapabilityManifest, getStoredUser, IntegrationConnectorItem, PolicyTier } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";
import { useCurrentUser } from "@/lib/useCurrentUser";

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
    <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
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
    <div className="space-y-8 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
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
              className={`p-6 rounded-2xl jarvis-glass-card border ${
                isCloudant ? "border-emerald-500/40 shadow-emerald-500/5 hover:border-emerald-500/60" : "border-purple-500/30 hover:border-pink-500/60"
              } transition-all duration-300 space-y-4 shadow-lg`}
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

      {/* Capability Manifest Registry Manager (§8) */}
      <CapabilityManifestRegistryPanel />

      {/* Integration Bus Specifications */}
      <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚙️</span>
            <h2 className="text-lg font-semibold text-text-primary">Integration Bus &amp; Substrate Specs</h2>
          </div>
          <span className="text-xs font-mono text-emerald px-2.5 py-1 rounded bg-emerald/10 border border-emerald/20">
            PostgreSQL &amp; Apache Kafka Active
          </span>
        </div>

        <div className="space-y-2 text-xs font-mono text-text-secondary">
          <p>
            All backend integration services execute against <code className="text-emerald">PostgreSQL 16</code> and <code className="text-cobalt">Apache Kafka (aiokafka)</code> for durable storage and EventEnvelope v2 delivery.
          </p>
          <div className="p-3 rounded-lg bg-glass border border-border-subtle space-y-1">
            <div className="text-text-primary">Primary Persistence Engine: <code className="text-purple">PostgreSQL 16 (db/ + Alembic migrations)</code></div>
            <div className="text-text-primary">Event Bus Substrate: <code className="text-cobalt">Apache Kafka (KRaft mode) / Redis Streams</code></div>
            <div className="text-text-primary">SSE Event Stream Endpoint: <code className="text-emerald">GET /api/v1/events/stream?token=...&amp;correlation_id=...</code></div>
          </div>
        </div>
      </div>
    </div>
  );
}

const LIFECYCLE_STAGES = [
  { name: "Proposed", badge: "PROPOSED", desc: "Tool or MCP repo declared; pending automated sandbox execution." },
  { name: "Sandbox Tested", badge: "SANDBOX_TESTED", desc: "Mock payloads executed; tamper-evident test evidence verified." },
  { name: "Active", badge: "ACTIVE", desc: "Promoted to active execution hub; gated by action-level governance." },
  { name: "Hot Disabled", badge: "HOT_DISABLED", desc: "Hot-switched off by administrator; blocked at Integration Hub." },
] as const;

// Literal class strings only (no `text-${color}` interpolation) - Tailwind's
// scanner needs the full class name to appear verbatim in source, see this
// file's own STAGES rewrite where `bg-red/20` (not a real design token,
// "status-red" is) silently generated no CSS at all.
const STATUS_BADGE_CLASS: Record<CapabilityManifest["status"], string> = {
  proposed: "bg-amber/20 text-amber border-amber/30",
  sandbox_tested: "bg-cyan/20 text-cyan border-cyan/30",
  active: "bg-emerald/20 text-emerald border-emerald/30",
  deprecated: "bg-glass text-text-secondary border-border-subtle",
  hot_disabled: "bg-status-red/20 text-status-red border-status-red/30",
};

const RISK_BADGE_CLASS: Record<CapabilityManifest["risk_level"], string> = {
  LOW: "bg-emerald/20 text-emerald border-emerald/30",
  MEDIUM: "bg-amber/20 text-amber border-amber/30",
  HIGH: "bg-status-red/20 text-status-red border-status-red/30",
};

function CapabilityManifestRegistryPanel() {
  const hasToken = useHasToken();
  const currentUser = useCurrentUser();
  const queryClient = useQueryClient();
  const canGovern = currentUser?.role === "admin" || currentUser?.role === "executive";

  const manifestsQuery = useQuery<CapabilityManifest[]>({
    queryKey: ["capability-manifests"],
    queryFn: api.getCapabilityManifests,
    enabled: hasToken,
    refetchInterval: 10000,
  });
  const manifests = manifestsQuery.data ?? [];

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["capability-manifests"] });
  const promoteMutation = useMutation({ mutationFn: api.promoteCapabilityManifest, onSuccess: invalidate });
  const disableMutation = useMutation({ mutationFn: api.disableCapabilityManifest, onSuccess: invalidate });

  return (
    <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="text-lg">📜</span>
          <h2 className="text-lg font-semibold text-text-primary">Capability Onboarding Lifecycle (§8)</h2>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/capability-onboarding"
            className="px-3.5 py-1.5 rounded-xl text-xs font-mono font-semibold bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white shadow-md shadow-purple-500/20 transition-all"
          >
            🚀 Launch BYOC Studio →
          </Link>
          <span className="text-xs font-mono text-purple px-2.5 py-1 rounded bg-purple/10 border border-purple/20">
            CapabilityManifestRegistry Model
          </span>
        </div>
      </div>

      <p className="text-xs text-text-secondary">
        Backend substrate capability lifecycle implemented in <code className="text-cobalt">integrations/capability_manifest.py</code>. External GitHub repos and MCP tools transition through 4 governance states before execution.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {LIFECYCLE_STAGES.map((s) => (
          <div key={s.badge} className="p-4 rounded-2xl jarvis-glass-card border border-purple-500/20 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sm text-text-primary">{s.name}</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${STATUS_BADGE_CLASS[s.badge.toLowerCase() as CapabilityManifest["status"]]}`}>
                {s.badge}
              </span>
            </div>
            <p className="text-xs text-text-secondary">{s.desc}</p>
          </div>
        ))}
      </div>

      <div className="pt-2 border-t border-border-subtle space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text-primary">Registered Capabilities</h3>
          <span className="text-xs font-mono text-text-secondary">{hasToken && manifestsQuery.data ? `${manifests.length} registered` : "—"}</span>
        </div>

        {!hasToken && <p className="text-sm text-status-red">Enter a service token above to load the manifest registry.</p>}
        {hasToken && manifestsQuery.isLoading && <p className="text-sm text-text-secondary">Loading capability manifests…</p>}
        {hasToken && manifestsQuery.isError && <p className="text-sm text-status-red">Could not load capability manifests (check backend &amp; service token).</p>}
        {hasToken && manifestsQuery.data && manifests.length === 0 && (
          <p className="text-xs text-text-secondary">
            No capabilities proposed yet. Proposals come from an onboarding agent, not an admin form (§8.3: the agent proposes, it never self-approves) — this list populates once something calls <code className="text-cobalt">registry.propose()</code>.
          </p>
        )}

        {manifests.map((m) => (
          <div key={m.capability_id} className="p-4 rounded-2xl jarvis-glass-card border border-purple-500/20 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-sm text-text-primary">{m.display_name}</span>
                <span className="text-[11px] font-mono text-text-secondary">{m.capability_id}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${STATUS_BADGE_CLASS[m.status]}`}>
                  {m.status.toUpperCase()}
                </span>
                <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${RISK_BADGE_CLASS[m.risk_level]}`}>
                  {m.risk_level}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] font-mono text-text-secondary">
              <div>Domain: <span className="text-text-primary">{m.domain}</span></div>
              <div>Version: <span className="text-text-primary">{m.version}</span></div>
              <div>Proposed by: <span className="text-text-primary">{m.proposed_by}</span></div>
              <div>Usage count: <span className="text-text-primary">{m.usage_count}</span></div>
            </div>
            <div className="text-[11px] font-mono text-text-secondary">Source: <span className="text-text-primary">{m.source}</span></div>
            <div className="text-[11px] font-mono text-text-secondary">
              Sandbox evidence: <span className="text-text-primary">{m.sandbox_evidence ?? "not yet tested"}</span>
            </div>
            <div className="text-[11px] font-mono text-text-secondary">Registered: {new Date(m.registered_at).toLocaleString()}</div>

            {canGovern && (m.status === "sandbox_tested" || m.status === "hot_disabled" || m.status === "active") && (
              <div className="pt-2 flex gap-2">
                {(m.status === "sandbox_tested" || m.status === "hot_disabled") && (
                  <button
                    onClick={() => promoteMutation.mutate(m.capability_id)}
                    disabled={promoteMutation.isPending}
                    className="px-3 py-1.5 rounded-lg text-xs font-mono bg-emerald/10 text-emerald border border-emerald/30 hover:bg-emerald/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {m.status === "hot_disabled" ? "Resume" : "Activate"}
                  </button>
                )}
                {m.status === "active" && (
                  <button
                    onClick={() => disableMutation.mutate(m.capability_id)}
                    disabled={disableMutation.isPending}
                    className="px-3 py-1.5 rounded-lg text-xs font-mono bg-status-red/10 text-status-red border border-status-red/30 hover:bg-status-red/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Hot-Disable
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}


