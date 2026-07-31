"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, EnterpriseIntelligenceSummary, KpiSummary, RiskSignal, StrategicRecommendation, WhatIfSimulation } from "@/lib/api";
import { KpiCard } from "@/components/design-system/KpiCard";
import { StatusPulse } from "@/components/design-system/StatusPulse";
import { useHasToken } from "@/lib/useHasToken";

function formatUsd(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function formatPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export default function ExecutiveEnterprisePage() {
  const [selectedCondition, setSelectedCondition] = useState("COND-TOL-DRIFT");
  const hasToken = useHasToken();

  const enterpriseQuery = useQuery<EnterpriseIntelligenceSummary>({
    queryKey: ["executive-enterprise"],
    queryFn: api.getEnterpriseSummary,
    refetchInterval: 15000,
    enabled: hasToken,
  });

  const kpisQuery = useQuery<KpiSummary>({
    queryKey: ["executive-kpis"],
    queryFn: api.getKpis,
    refetchInterval: 15000,
    enabled: hasToken,
  });

  const whatIfQuery = useQuery<WhatIfSimulation>({
    queryKey: ["executive-what-if", selectedCondition],
    queryFn: () => api.getWhatIf(selectedCondition),
    enabled: hasToken,
  });

  const riskQuery = useQuery<RiskSignal[]>({
    queryKey: ["executive-risk"],
    queryFn: api.getRiskSignals,
    refetchInterval: 15000,
    enabled: hasToken,
  });

  const recsQuery = useQuery<StrategicRecommendation[]>({
    queryKey: ["executive-recommendations"],
    queryFn: api.getStrategicRecommendations,
    enabled: hasToken,
  });

  const summary = enterpriseQuery.data;
  const kpis = kpisQuery.data;
  const whatIf = whatIfQuery.data;
  const risks = riskQuery.data ?? [];
  const recs = recsQuery.data ?? [];

  const kpiDataError = !hasToken || enterpriseQuery.isError || kpisQuery.isError;
  const kpiDataLoading = hasToken && (enterpriseQuery.isLoading || kpisQuery.isLoading);

  return (
    <div className="space-y-8 pb-12">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-orbitron font-extrabold text-white tracking-wide">
              Executive Intelligence Command Center
            </h1>
            <span className="px-3 py-1 rounded-full text-xs font-mono bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.3)]">
              Plant 04 - Bangalore
            </span>
          </div>
          <p className="text-xs sm:text-sm text-purple-200/70 mt-2 font-sans">
            Enterprise decision intelligence, P&amp;L revenue protection, and autonomous policy simulation.
          </p>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono shrink-0">
          <div className="flex items-center gap-2 px-4 py-2 rounded-2xl bg-purple-950/60 border border-purple-500/30 shadow-inner">
            <StatusPulse status={kpiDataError ? "critical" : "healthy"} label={kpiDataError ? "System Status: NO DATA" : "System Status: OPTIMAL"} />
          </div>
        </div>
      </div>

      {kpiDataLoading && <p className="text-sm text-purple-200/70 font-mono">Loading enterprise intelligence…</p>}
      {kpiDataError && <p className="text-sm text-red-400 font-mono">Could not load enterprise intelligence (check token).</p>}

      {/* KPI Cards Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <KpiCard
          label="Revenue Protected"
          value={formatUsd(summary?.revenueProtectedUsd ?? kpis?.revenueProtectedUsd)}
          trend="Protected vs downtime"
          accentColor="emerald"
        />

        <KpiCard
          label="Mean Time To Recovery"
          value={(summary?.mttrAvgMinutes ?? kpis?.mttrAvgMinutes) != null ? `${(summary?.mttrAvgMinutes ?? kpis!.mttrAvgMinutes).toFixed(1)}m` : "—"}
          trend="Avg across resolved incidents"
          accentColor="cobalt"
        />

        <KpiCard
          label="Autonomy Index"
          value={formatPct(summary?.autonomyIndex ?? kpis?.autonomyIndex)}
          trend="Tier 0 autonomous (Target: 90%)"
          accentColor="purple"
        />

        <KpiCard
          label="Recommendation Acceptance"
          value={formatPct(summary?.recommendationAcceptanceRate ?? kpis?.recommendationAcceptanceRate)}
          trend="Engineer 1-click approvals"
          accentColor="amber"
        />
      </div>

      {/* Operational KPI Cards — same three metrics /digital-twin's Twin
          Room header shows, backed by the same api.getKpis() totals rather
          than the session-local incident store, so this reflects the
          plant-wide count regardless of what this browser tab has seen. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        <KpiCard
          label="Production Health"
          value={kpis && kpis.totalIncidents > 0 ? `${Math.round((kpis.resolvedIncidents / kpis.totalIncidents) * 100)}%` : "100%"}
          trend="Resolved vs total incidents"
          accentColor="emerald"
        />

        <KpiCard
          label="Open Incidents"
          value={kpis ? String(Math.max(0, kpis.totalIncidents - kpis.resolvedIncidents - kpis.failedIncidents)) : "—"}
          trend="Not yet in a terminal state"
          accentColor={kpis && kpis.totalIncidents - kpis.resolvedIncidents - kpis.failedIncidents > 0 ? "status-red" : "emerald"}
        />

        <KpiCard
          label="Autonomous Decisions"
          value={String(kpis?.tierDistribution?.["Tier 0 (Autonomous)"] ?? 0)}
          trend="Tier 0 — no human in the loop"
          accentColor="purple"
        />
      </div>

      {/* What-If Autonomy Simulator & Risk Signals Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* What-If Autonomy Simulator */}
        <div className="lg:col-span-7 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-2xl">📈</span>
              <h2 className="text-xl font-orbitron font-bold text-white">What-If Autonomy Simulator</h2>
            </div>
            <span className="text-xs font-mono text-cyan-300 px-3 py-1 rounded-full bg-cyan-500/20 border border-cyan-500/40 shadow-[0_0_12px_rgba(6,182,212,0.3)]">
              Live Policy Engine
            </span>
          </div>

          <p className="text-xs text-purple-200/70 font-sans leading-relaxed">
            Simulate the operational and financial outcome of recalibrating causal thresholds across failure conditions.
          </p>

          {/* Condition Selector Tabs */}
          <div className="flex flex-wrap gap-2.5 pt-1">
            {[
              { id: "COND-TOL-DRIFT", label: "Tolerance Drift" },
              { id: "COND-HUMIDITY-SPIKE", label: "Humidity Spike" },
              { id: "COND-SPINDLE-VIB", label: "Spindle Vibration" },
              { id: "COND-MATERIAL-DEFECT", label: "Material Inclusion" },
            ].map((cond) => (
              <button
                key={cond.id}
                onClick={() => setSelectedCondition(cond.id)}
                className={`px-4 py-2 text-xs font-mono rounded-xl transition-all border ${
                  selectedCondition === cond.id
                    ? "novus-tab-active"
                    : "novus-tab-inactive"
                }`}
              >
                {cond.label}
              </button>
            ))}
          </div>

          {/* Simulation Output Display */}
          <div className="mt-4 p-5 rounded-2xl bg-purple-950/50 border border-purple-500/25 space-y-4 shadow-inner">
            <div className="flex justify-between items-center text-xs font-mono">
              <span className="text-purple-300/60">SIMULATED TARGET CONDITION:</span>
              <span className="text-pink-400 font-bold tracking-wider">{selectedCondition}</span>
            </div>

            {whatIfQuery.isLoading && <div className="text-xs text-purple-200/70 font-mono">Simulating outcome…</div>}
            {whatIfQuery.isError && <div className="text-xs text-red-400 font-mono">Could not run simulation (check token).</div>}

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 pt-2">
              <div className="p-4 rounded-xl bg-[#08051a]/80 border border-purple-500/20">
                <div className="text-xs text-purple-300/70 font-mono uppercase">Projected MTTR</div>
                <div className="text-xl font-orbitron font-bold text-emerald-400 mt-1">
                  {whatIf ? `${whatIf.simulated.mttr_avg_min.toFixed(1)}m` : "—"}
                </div>
              </div>

              <div className="p-4 rounded-xl bg-[#08051a]/80 border border-purple-500/20">
                <div className="text-xs text-purple-300/70 font-mono uppercase">Revenue Protected</div>
                <div className="text-xl font-orbitron font-bold text-cyan-400 mt-1">{formatUsd(whatIf?.simulated.revenue_protected_usd)}</div>
              </div>

              <div className="p-4 rounded-xl bg-[#08051a]/80 border border-purple-500/20 col-span-2 sm:col-span-1">
                <div className="text-xs text-purple-300/70 font-mono uppercase">Autonomy %</div>
                <div className="text-xl font-orbitron font-bold text-pink-400 mt-1">{formatPct(whatIf?.simulated.autonomy_index)}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Predictive Risk Radar */}
        <div className="lg:col-span-5 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-2xl">🛡️</span>
              <h2 className="text-xl font-orbitron font-bold text-white">Predictive Risk Radar</h2>
            </div>
            <span className="text-xs font-mono text-amber-300 px-3 py-1 rounded-full bg-amber-500/20 border border-amber-500/40">
              {risks.length} Signals
            </span>
          </div>

          <div className="space-y-4 max-h-[340px] overflow-y-auto pr-1">
            {riskQuery.isLoading ? (
              <div className="text-xs text-purple-200/60 py-6 text-center font-mono">Loading risk signals…</div>
            ) : riskQuery.isError ? (
              <div className="text-xs text-red-400 py-6 text-center font-mono">Could not load risk signals (check token).</div>
            ) : risks.length === 0 ? (
              <div className="text-xs text-purple-200/60 py-6 text-center font-mono">No active risk signals detected.</div>
            ) : (
              risks.map((risk) => (
                <div key={risk.signalId} className="p-4 rounded-2xl bg-purple-950/40 border border-purple-500/25 space-y-2 hover:border-pink-500/40 transition-colors">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-white font-bold tracking-wider">{risk.lineId}</span>
                    <span
                      className={`px-2.5 py-1 rounded-lg text-[10px] font-bold font-mono tracking-wider ${
                        risk.risk_level === "CRITICAL"
                          ? "bg-red-500/20 text-red-300 border border-red-500/40 shadow-[0_0_10px_rgba(239,68,68,0.4)]"
                          : risk.risk_level === "ELEVATED"
                          ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-[0_0_10px_rgba(245,158,11,0.4)]"
                          : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-[0_0_10px_rgba(16,185,129,0.4)]"
                      }`}
                    >
                      {risk.risk_level} ({(risk.risk_score * 100).toFixed(0)}%)
                    </span>
                  </div>
                  <div className="text-xs text-purple-200/80 font-sans">{risk.primaryRiskDriver}</div>
                  <div className="text-[11px] font-mono text-cyan-300 pt-1">
                    Mitigation: {risk.recommendedMitigation}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Strategic Recommendations */}
      <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">💡</span>
            <h2 className="text-xl font-orbitron font-bold text-white">Strategic Recommendations</h2>
          </div>
          <span className="text-xs font-mono text-emerald-300 px-3 py-1 rounded-full bg-emerald-500/20 border border-emerald-500/40">
            {recs.length} Recommendations Generated
          </span>
        </div>

        {recsQuery.isLoading && <p className="text-xs text-purple-200/60 font-mono">Loading recommendations…</p>}
        {recsQuery.isError && <p className="text-xs text-red-400 font-mono">Could not load recommendations (check token).</p>}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {recs.map((rec) => (
            <div key={rec.recommendationId} className="p-6 rounded-2xl bg-purple-950/40 border border-purple-500/25 space-y-3 hover:border-pink-500/40 transition-colors">
              <div className="flex items-center justify-between gap-2">
                <span className="px-2.5 py-1 rounded-lg text-[10px] font-mono bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 uppercase tracking-wider">
                  {rec.category}
                </span>
                <span className="text-xs font-orbitron font-bold text-emerald-400 drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]">
                  +${rec.estimatedAnnualSavingsUsd?.toLocaleString()} / yr
                </span>
              </div>
              <h3 className="text-base font-orbitron font-bold text-white">{rec.title}</h3>
              <p className="text-xs text-purple-200/70 font-sans leading-relaxed">{rec.summary}</p>
              {rec.actionItems && rec.actionItems.length > 0 && (
                <div className="pt-2">
                  <div className="text-[11px] font-mono text-pink-300/80 mb-1.5 uppercase tracking-wider">Action Plan:</div>
                  <ul className="list-disc list-inside text-xs text-purple-100 space-y-1 font-sans">
                    {rec.actionItems.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

