"use client";

import { useQuery } from "@tanstack/react-query";
import { api, GovernancePolicies } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

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
              Holds execution in the approval queue until an authorized user's approval_limit_usd covers the cost.
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
            <div className="text-text-secondary mb-1.5">watsonx Orchestrate ITSM live-write gate ({policies.itsmLiveWriteGate.source}):</div>
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
    </div>
  );
}
