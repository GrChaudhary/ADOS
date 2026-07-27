"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, PolicyPromotionCandidate, WhatIfSimulation } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

interface CustomPolicyRule {
  id: string;
  code: string;
  name: string;
  condition: string;
  actionTier: "Tier 0 (Autonomous)" | "Tier 1 (Engineer Approval)" | "Tier 2 (Executive Signature)";
  enabled: boolean;
  notes: string;
}

const LOCAL_STORAGE_KEY = "ados_custom_policies";

export default function PolicyStudioPage() {
  const hasToken = useHasToken();
  const [customRules, setCustomRules] = useState<CustomPolicyRule[]>([]);
  const [newRuleName, setNewRuleName] = useState("Custom Emergency Guardrail");
  const [newCondition, setNewCondition] = useState("Cost > $50,000");
  const [newTier, setNewTier] = useState<CustomPolicyRule["actionTier"]>("Tier 1 (Engineer Approval)");
  const [simCondition, setSimCondition] = useState("COND-TOL-DRIFT");

  // Load custom policies from localStorage on mount. Genuinely one-time,
  // local-only hydration with no other writer/subscriber to synchronize
  // with (unlike the token/persona stores, which useSyncExternalStore
  // handles elsewhere in this app) - SSR always renders customRules=[],
  // and this only ever runs after mount, so it can't produce a hydration
  // mismatch despite the lint rule's general caution here.
  useEffect(() => {
    try {
      const stored = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (stored) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setCustomRules(JSON.parse(stored));
      }
    } catch (err) {
      console.error("Failed to load custom policies", err);
    }
  }, []);

  // Sync custom policies to localStorage
  const saveRules = (newRules: CustomPolicyRule[]) => {
    setCustomRules(newRules);
    try {
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(newRules));
    } catch (err) {
      console.error("Failed to save custom policies", err);
    }
  };

  // Fetch real backend promotion candidates evaluated from Decision Memory audit history
  const candidatesQuery = useQuery<PolicyPromotionCandidate[]>({
    queryKey: ["policy-promotion-candidates"],
    queryFn: api.getPromotionCandidates,
    enabled: hasToken,
  });

  // Fetch real backend what-if simulation from KPIEngine
  const whatIfQuery = useQuery<WhatIfSimulation>({
    queryKey: ["policy-what-if-sim", simCondition],
    queryFn: () => api.getWhatIf(simCondition),
    enabled: hasToken,
  });

  const candidates = candidatesQuery.data ?? [];
  const whatIf = whatIfQuery.data;

  const handleAddRule = (e: React.FormEvent) => {
    e.preventDefault();
    const created: CustomPolicyRule = {
      id: `rule-${Date.now()}`,
      code: `POL-CST-${customRules.length + 1}`,
      name: newRuleName,
      condition: newCondition,
      actionTier: newTier,
      enabled: true,
      notes: "Custom policy rule created via Policy Studio visual editor.",
    };
    saveRules([...customRules, created]);
  };

  const toggleRule = (id: string) => {
    saveRules(customRules.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)));
  };

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Policy Studio</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-purple/10 text-purple border border-purple/30">
              Layer 5 Governance Engine
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            No-code visual rule builder, backend promotion candidates evaluation, and dynamic what-if simulation engine.
          </p>
        </div>
      </div>

      {/* Visual Rule Builder & Live What-If Simulator Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Visual Rule Creation Builder */}
        <div className="lg:col-span-7 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🛠️</span>
              <h2 className="text-lg font-semibold text-text-primary">Visual Policy Rule Builder</h2>
            </div>
            <span className="text-xs font-mono text-cobalt px-2.5 py-1 rounded bg-cobalt/10 border border-cobalt/20">
              No-Code Editor
            </span>
          </div>

          <form onSubmit={handleAddRule} className="space-y-4 pt-1">
            <div>
              <label className="block text-xs font-mono text-text-secondary mb-1">Rule Name</label>
              <input
                type="text"
                value={newRuleName}
                onChange={(e) => setNewRuleName(e.target.value)}
                className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-mono text-text-secondary mb-1">IF Condition</label>
                <input
                  type="text"
                  value={newCondition}
                  onChange={(e) => setNewCondition(e.target.value)}
                  className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-mono text-text-secondary mb-1">THEN Action Tier</label>
                <select
                  value={newTier}
                  onChange={(e) => setNewTier(e.target.value as CustomPolicyRule["actionTier"])}
                  className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
                >
                  <option value="Tier 0 (Autonomous)">Tier 0 (Autonomous)</option>
                  <option value="Tier 1 (Engineer Approval)">Tier 1 (Engineer Approval)</option>
                  <option value="Tier 2 (Executive Signature)">Tier 2 (Executive Signature)</option>
                </select>
              </div>
            </div>

            <button
              type="submit"
              className="w-full px-4 py-2.5 text-xs font-mono font-semibold rounded-lg bg-purple text-white hover:bg-purple/80 transition-all border border-purple/40"
            >
              + Deploy Custom Governance Rule to Local Storage
            </button>
          </form>
        </div>

        {/* Live Backend Policy Simulator */}
        <div className="lg:col-span-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🧪</span>
              <h2 className="text-base font-semibold text-text-primary">Backend Policy Simulator</h2>
            </div>
            <span className="text-xs font-mono text-emerald px-2 py-0.5 rounded bg-emerald/10 border border-emerald/20">
              Live FastAPI Wire
            </span>
          </div>

          <div className="space-y-3 font-mono text-xs">
            <div>
              <label className="block text-text-secondary mb-1">Target Failure Condition ID</label>
              <select
                value={simCondition}
                onChange={(e) => setSimCondition(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
              >
                <option value="COND-TOL-DRIFT">COND-TOL-DRIFT (Tolerance Drift)</option>
                <option value="COND-HUMIDITY-SPIKE">COND-HUMIDITY-SPIKE (Humidity Spike)</option>
                <option value="COND-SPINDLE-VIB">COND-SPINDLE-VIB (Spindle Vibration)</option>
                <option value="COND-MATERIAL-DEFECT">COND-MATERIAL-DEFECT (Material Inclusion)</option>
              </select>
            </div>

            <div className="p-3 rounded-lg bg-glass border border-border-subtle space-y-2">
              <div className="text-text-secondary text-[11px]">Backend KPIEngine Simulation Result:</div>
              {!hasToken && <div className="text-text-secondary text-[11px]">Enter a service token to run the simulation.</div>}
              {hasToken && whatIfQuery.isLoading && <div className="text-text-secondary text-[11px]">Simulating…</div>}
              {hasToken && whatIfQuery.isError && <div className="text-status-red text-[11px]">Could not run simulation (check token).</div>}
              {whatIf && (
                <>
                  <div className="flex justify-between">
                    <span>Simulated MTTR:</span>
                    <span className="text-emerald font-bold">{whatIf.simulated.mttr_avg_min.toFixed(1)}m</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Revenue Protected:</span>
                    <span className="text-emerald font-bold">${whatIf.simulated.revenue_protected_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                  </div>
                  <div className="flex justify-between">
                    <span>Autonomy Ratio:</span>
                    <span className="text-purple font-bold">{(whatIf.simulated.autonomy_index * 100).toFixed(1)}%</span>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Backend Evaluated Tier 0 Promotion Candidates */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">🚀</span>
            <h2 className="text-lg font-semibold text-text-primary">Backend Tier 0 Promotion Candidates</h2>
          </div>
          <span className="text-xs font-mono text-emerald px-2.5 py-1 rounded bg-emerald/10 border border-emerald/20">
            {candidates.length} Evaluated Candidates
          </span>
        </div>

        <div className="space-y-3 font-mono text-xs">
          {hasToken && candidatesQuery.isLoading && (
            <div className="text-text-secondary py-4 text-center">Loading candidates…</div>
          )}
          {hasToken && candidatesQuery.isError && (
            <div className="text-status-red py-4 text-center">Could not load candidates (check token).</div>
          )}
          {hasToken && !candidatesQuery.isLoading && !candidatesQuery.isError && candidates.length === 0 ? (
            <div className="text-text-secondary py-4 text-center">No policy promotion candidates evaluated.</div>
          ) : (
            candidates.map((cand) => (
              <div key={cand.candidateId} className="p-4 rounded-lg bg-glass border border-border-subtle space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-text-primary">{cand.decisionClassName}</span>
                    <span className="text-text-secondary text-[11px]">({cand.conditionId})</span>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      cand.isEligible ? "bg-emerald/20 text-emerald border border-emerald/40" : "bg-amber/20 text-amber border border-amber/40"
                    }`}
                  >
                    {cand.isEligible ? "ELIGIBLE FOR TIER 0" : "EVALUATING"}
                  </span>
                </div>

                <div className="text-text-secondary text-[11px]">{cand.promotionRationale}</div>

                {cand.safetyGuardrails && cand.safetyGuardrails.length > 0 && (
                  <div className="pt-1 flex flex-wrap gap-1.5">
                    {cand.safetyGuardrails.map((g, idx) => (
                      <span key={idx} className="px-2 py-0.5 rounded text-[10px] bg-cobalt/10 text-cobalt border border-cobalt/20">
                        Guardrail: {g}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* User-Created Custom Policies */}
      {customRules.length > 0 && (
        <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">💾</span>
              <h2 className="text-lg font-semibold text-text-primary">Deployed Custom User Policies</h2>
            </div>
            <span className="text-xs font-mono text-purple px-2 py-0.5 rounded bg-purple/10 border border-purple/20">
              Local Storage Persisted
            </span>
          </div>

          <div className="space-y-3">
            {customRules.map((rule) => (
              <div
                key={rule.id}
                className="p-4 rounded-lg bg-glass border border-border-subtle flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs font-mono"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-cobalt">{rule.code}:</span>
                    <span className="font-semibold text-text-primary">{rule.name}</span>
                    <span className="px-2 py-0.5 rounded text-[10px] bg-purple/20 text-purple border border-purple/40">
                      {rule.actionTier}
                    </span>
                  </div>
                  <div className="text-text-secondary">IF: <code className="text-mono text-text-primary">{rule.condition}</code></div>
                </div>

                <div className="flex items-center gap-3">
                  <span className={`text-[11px] font-bold ${rule.enabled ? "text-emerald" : "text-text-secondary"}`}>
                    {rule.enabled ? "ACTIVE" : "DISABLED"}
                  </span>
                  <button
                    onClick={() => toggleRule(rule.id)}
                    className={`w-10 h-5 rounded-full transition-all relative ${
                      rule.enabled ? "bg-emerald" : "bg-border-subtle"
                    }`}
                  >
                    <div
                      className={`w-4 h-4 rounded-full bg-white transition-all absolute top-0.5 ${
                        rule.enabled ? "right-0.5" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
