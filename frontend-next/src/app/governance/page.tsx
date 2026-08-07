"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, CircuitBreakerStatus, GovernancePolicies } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";
import { useCurrentUser } from "@/lib/useCurrentUser";

export default function GovernancePolicyPage() {
  const hasToken = useHasToken();

  // Real backend data (backend/app/routers/governance.py) - previously
  // this page's "Enforced Policy Rules" panel was a hardcoded array with
  // no backend behind it at all (one entry, POL-004, had no enforcing
  // code anywhere in the repo). Every value below is read straight from
  // the modules that actually enforce it.
  const policiesQuery = useQuery<GovernancePolicies>({
    queryKey: ["governance-policies"],
    queryFn: api.getGovernancePolicies,
    enabled: hasToken,
  });
  const policies = policiesQuery.data;

  const lowExposureMaxUsd = policies?.financialExposureBands.lowExposureMaxUsd ?? 0;
  const highExposureMinUsd = policies?.financialExposureBands.highExposureMinUsd ?? 0;
  const tier0ConfidenceThreshold = policies?.financialExposureBands.tier0ConfidenceThreshold ?? 0;

  return (
    <div className="space-y-8 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Governance Policy &amp; Autonomy Administration</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-purple/10 text-purple border border-purple/30">
              Layer 5 Policy Engine
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Financial exposure tier thresholds and the RBAC rules that actually gate approve/reject/escalate — read live from the backend, not illustrative.
          </p>
        </div>
      </div>

      {!hasToken && <p className="text-sm text-text-secondary">Log in to load governance policy data.</p>}
      {hasToken && policiesQuery.isLoading && <p className="text-sm text-text-secondary">Loading policy data…</p>}
      {hasToken && policiesQuery.isError && <p className="text-sm text-status-red">Could not load governance policies.</p>}

      {/* Dollar-Threshold Tier Matrix */}
      <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚖️</span>
            <h2 className="text-lg font-semibold text-text-primary">Dollar-Threshold Governance Matrix</h2>
          </div>
          <span className="text-xs font-mono text-text-secondary">
            Source: <code className="text-cobalt">{policies?.financialExposureBands.source ?? "orchestrate/governance.py"}</code>
          </span>
        </div>

        <p className="text-xs text-text-secondary">
          The Governance Policy Engine evaluates every capability call against financial exposure boundaries and AI agent confidence.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
          {/* Tier 0 Card */}
          <div className="p-5 rounded-2xl jarvis-glass-card border border-emerald-500/30 hover:border-emerald-500/60 space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
              <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-emerald/20 text-emerald border border-emerald/40">
                TIER 0
              </span>
              <span className="text-xs font-mono text-emerald font-semibold">Fully Autonomous</span>
            </div>
            <div className="space-y-1 font-mono text-xs">
              <div className="text-text-secondary">Max Cost: <span className="text-text-primary font-bold">&lt; ${lowExposureMaxUsd.toLocaleString("en-US")}</span></div>
              <div className="text-text-secondary">Min Confidence: <span className="text-text-primary font-bold">&gt; {(tier0ConfidenceThreshold * 100).toFixed(0)}%</span></div>
            </div>
            <p className="text-[11px] text-text-secondary">
              Dispatches execution immediately without human intervention.
            </p>
          </div>

          {/* Tier 1 Card */}
          <div className="p-5 rounded-2xl jarvis-glass-card border border-cyan-500/30 hover:border-cyan-500/60 space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
              <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-cobalt/20 text-cobalt border border-cobalt/40">
                TIER 1
              </span>
              <span className="text-xs font-mono text-cobalt font-semibold">Manager Approval</span>
            </div>
            <div className="space-y-1 font-mono text-xs">
              <div className="text-text-secondary">Cost Range: <span className="text-text-primary font-bold">${lowExposureMaxUsd.toLocaleString("en-US")} – ${highExposureMinUsd.toLocaleString("en-US")}</span></div>
              <div className="text-text-secondary">Required Role: <span className="text-text-primary font-bold">manager / executive / admin</span></div>
            </div>
            <p className="text-[11px] text-text-secondary">
              Holds execution in the approval queue until an authorized user&apos;s approval_limit_usd covers the cost.
            </p>
          </div>

          {/* Tier 2 Card */}
          <div className="p-5 rounded-2xl jarvis-glass-card border border-pink-500/30 hover:border-pink-500/60 space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
              <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-purple/20 text-purple border border-purple/40">
                TIER 2
              </span>
              <span className="text-xs font-mono text-purple font-semibold">Executive Approval</span>
            </div>
            <div className="space-y-1 font-mono text-xs">
              <div className="text-text-secondary">Cost Range: <span className="text-text-primary font-bold">&gt; ${highExposureMinUsd.toLocaleString("en-US")}</span></div>
              <div className="text-text-secondary">Required Role: <span className="text-text-primary font-bold">executive / admin</span></div>
            </div>
            <p className="text-[11px] text-text-secondary">
              Manager-role users cannot decide these regardless of approval_limit_usd — enforced server-side.
            </p>
          </div>
        </div>
      </div>

      {/* Real RBAC + Governance Rule Enforcements */}
      <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📋</span>
            <h2 className="text-lg font-semibold text-text-primary">Enforced Policy Rules</h2>
          </div>
          <span className="text-xs font-mono text-emerald px-2 py-0.5 rounded bg-emerald/10 border border-emerald/20">
            Live from backend/app/routers/governance.py
          </span>
        </div>

        <div className="space-y-2 text-xs font-mono">
          {(policies?.rbacApprovalRules ?? []).map((rule, idx) => (
            <div key={idx} className="p-3 rounded-xl jarvis-glass-card border border-purple-500/20 hover:border-pink-500/40 flex items-center justify-between gap-4 shadow-sm">
              <span className="text-text-primary">{rule}</span>
              <span className="px-2 py-0.5 rounded text-[10px] bg-emerald/20 text-emerald font-bold">ACTIVE</span>
            </div>
          ))}
        </div>

        {policies && (
          <div className="pt-2 border-t border-border-subtle text-xs font-mono">
            <div className="text-text-secondary mb-1.5">ServiceNow ITSM connector gate ({policies.itsmLiveWriteGate.source}):</div>
            <div className="flex gap-4">
              <span className={policies.itsmLiveWriteGate.connectorEligible ? "text-emerald" : "text-text-secondary"}>
                Connector eligible: {String(policies.itsmLiveWriteGate.connectorEligible)}
              </span>
              <span className={policies.itsmLiveWriteGate.liveWritesEnabled ? "text-status-red font-bold" : "text-text-secondary"}>
                Live writes enabled: {String(policies.itsmLiveWriteGate.liveWritesEnabled)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Capability Risk Class Map (Live from /governance/policies) */}
      <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">🎯</span>
            <h2 className="text-lg font-semibold text-text-primary">Capability Risk Classifications</h2>
          </div>
          <span className="text-xs font-mono text-purple px-2 py-0.5 rounded bg-purple/10 border border-purple/20">
            Live from policies.capabilityRiskClass
          </span>
        </div>

        <p className="text-xs text-text-secondary">
          Every action capability is classified by risk class (low, medium, high, critical) which determines the required governance approval tier.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 text-xs font-mono">
          {Object.entries(policies?.capabilityRiskClass ?? {}).map(([cap, risk]) => {
            const isHigh = risk === "high" || risk === "critical";
            const isMedium = risk === "medium";
            return (
              <div key={cap} className="p-3 rounded-xl jarvis-glass-card border border-purple-500/20 flex items-center justify-between gap-2 shadow-sm">
                <span className="text-text-primary font-medium truncate">{cap}</span>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                    isHigh
                      ? "bg-status-red/20 text-status-red border border-status-red/30"
                      : isMedium
                      ? "bg-amber/20 text-amber border border-amber/30"
                      : "bg-emerald/20 text-emerald border border-emerald/30"
                  }`}
                >
                  {risk}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Cascade Circuit Breaker Monitor Card (Honest Architecture State) */}
      <CircuitBreakerCard />

      {/* Obsidian Vault Architecture Graph Card (§9) */}
      <ObsidianProjectionCard />
    </div>
  );
}

function ObsidianProjectionCard() {
  const hasToken = useHasToken();
  const currentUser = useCurrentUser();
  const queryClient = useQueryClient();
  const canGenerate = Boolean(currentUser) && currentUser?.role !== "auditor";
  const [result, setResult] = useState<{ status: string; target_dir?: string; reconciled_files_count?: number; total_vault_notes?: number } | null>(null);

  const statusQuery = useQuery({
    queryKey: ["obsidian-projection-status"],
    queryFn: api.getObsidianProjectionStatus,
    enabled: hasToken,
    refetchInterval: 5000,
  });
  const vaultStats = statusQuery.data;

  const projectionMutation = useMutation({
    mutationFn: api.generateObsidianProjection,
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ["obsidian-projection-status"] });
    },
  });

  const syncMutation = useMutation({
    mutationFn: api.syncObsidianVault,
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ["obsidian-projection-status"] });
    },
  });

  return (
    <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🕸️</span>
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Real-Time Obsidian Projection &amp; Live Vault (§9)</h2>
            <p className="text-xs text-text-secondary mt-0.5">
              Event-driven background listener projects live MOA trajectories, governance decisions, dynamic capabilities, and native `.canvas` flowcharts into `ADOS_OBSIDIAN/Platform_Graph/`.
            </p>
          </div>
        </div>

        <span className="px-3 py-1 rounded-full text-xs font-mono font-bold bg-purple/20 text-purple border border-purple/40">
          {vaultStats?.status === "active" ? "🟢 LIVE LISTENER ACTIVE" : "IDLE"}
        </span>
      </div>

      {hasToken && vaultStats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 font-mono text-xs">
          <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-1">
            <div className="text-text-secondary">Total Vault Notes:</div>
            <div className="text-base font-bold text-text-primary">{vaultStats.totalNotesCount}</div>
            <div className="text-[11px] text-text-secondary">Markdown &amp; .canvas files</div>
          </div>

          <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-1">
            <div className="text-text-secondary">Projected Events:</div>
            <div className="text-base font-bold text-emerald">{vaultStats.projectedEventsCount}</div>
            <div className="text-[11px] text-text-secondary">Background written events</div>
          </div>

          <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-1">
            <div className="text-text-secondary">Listener Queue Depth:</div>
            <div className="text-base font-bold text-purple">{vaultStats.queueDepth}</div>
            <div className="text-[11px] text-text-secondary">Events pending flush</div>
          </div>

          <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-1">
            <div className="text-text-secondary">Obsidian REST API:</div>
            <div className="text-base font-bold text-cobalt">{vaultStats.localRestApiEnabled ? "CONNECTED" : "OFFLINE"}</div>
            <div className="text-[11px] text-text-secondary">Remote HTTPS sync status</div>
          </div>
        </div>
      )}

      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-4 border-t border-border-subtle">
        <div className="text-xs font-mono text-text-secondary truncate max-w-md">
          {result ? (
            <span className="text-emerald">
              ✓ Synced {result.reconciled_files_count ?? (result as { generated_notes_count?: number }).generated_notes_count ?? 0} vault file(s) into {result.target_dir}
            </span>
          ) : (
            `Vault Location: ${vaultStats?.targetDir || "ADOS_OBSIDIAN/Platform_Graph"}`
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => projectionMutation.mutate()}
            disabled={!hasToken || !canGenerate || projectionMutation.isPending || syncMutation.isPending}
            className="px-4 py-2 rounded-xl bg-purple-600/80 hover:bg-purple-500 text-white font-medium text-xs shadow-lg shadow-purple-500/25 disabled:opacity-50 transition-all"
          >
            {projectionMutation.isPending ? "Generating…" : "Refresh Graph Notes"}
          </button>

          <button
            onClick={() => syncMutation.mutate()}
            disabled={!hasToken || !canGenerate || syncMutation.isPending || projectionMutation.isPending}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-medium text-xs shadow-lg shadow-emerald-500/20 disabled:opacity-50 transition-all"
          >
            {syncMutation.isPending ? "Syncing Vault…" : "Sync DB to Vault"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CircuitBreakerCard() {
  const hasToken = useHasToken();
  const currentUser = useCurrentUser();
  const queryClient = useQueryClient();
  const canClear = Boolean(currentUser) && currentUser?.role !== "auditor";

  const statusQuery = useQuery<CircuitBreakerStatus>({
    queryKey: ["circuit-breaker-status"],
    queryFn: api.getCircuitBreakerStatus,
    enabled: hasToken,
    refetchInterval: 5000,
  });
  const status = statusQuery.data;
  const isOpen = status?.state === "OPEN";

  const clearMutation = useMutation({
    mutationFn: api.clearCircuitBreaker,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["circuit-breaker-status"] }),
  });

  return (
    <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">⚡</span>
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Cascade Circuit Breaker</h2>
            <p className="text-xs text-text-secondary mt-0.5">
              MOA creates one CascadeCircuitBreaker per task (not a single global instance) — the numbers below are an honest aggregate across whichever MOA tasks are currently live/paused, not a fabricated global counter.
            </p>
          </div>
        </div>

        <span
          className={`px-3 py-1 rounded-full text-xs font-mono font-bold border ${
            isOpen ? "bg-status-red/20 text-status-red border-status-red/40" : "bg-emerald/20 text-emerald border-emerald/40"
          }`}
        >
          {hasToken && status ? status.state : "—"}
        </span>
      </div>

      {!hasToken && <p className="text-sm text-status-red">Enter a service token above to load circuit breaker status.</p>}
      {hasToken && statusQuery.isLoading && <p className="text-sm text-text-secondary">Loading circuit breaker status…</p>}
      {hasToken && statusQuery.isError && <p className="text-sm text-status-red">Could not load circuit breaker status (check backend &amp; service token).</p>}

      {hasToken && status && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
            <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-1">
              <div className="text-text-secondary">Auto-Approved Streak:</div>
              <div className="text-sm font-bold text-text-primary">{status.auto_approved_count} / {status.threshold}</div>
              <div className="text-[11px] text-text-secondary">Consecutive autonomous-tier actions before escalation</div>
            </div>

            <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-1">
              <div className="text-text-secondary">Active MOA Tasks:</div>
              <div className="text-sm font-bold text-purple">{status.active_tasks}</div>
              <div className="text-[11px] text-text-secondary">Tasks currently paused awaiting a human</div>
            </div>

            <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-1">
              <div className="text-text-secondary">Open Task IDs:</div>
              <div className="text-sm font-bold text-text-primary truncate">
                {status.open_task_ids.length > 0 ? status.open_task_ids.join(", ") : "none"}
              </div>
              <div className="text-[11px] text-text-secondary">Breakers currently tripped OPEN</div>
            </div>
          </div>

          {canClear && isOpen && (
            <div className="pt-2 border-t border-border-subtle">
              <button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="px-3 py-1.5 rounded-lg text-xs font-mono bg-status-red/10 text-status-red border border-status-red/30 hover:bg-status-red/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {clearMutation.isPending ? "Clearing…" : "Clear after review"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}


