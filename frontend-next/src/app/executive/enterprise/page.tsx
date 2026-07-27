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
    <div className="space-y-6 pb-8">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Executive Intelligence Command Center</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald/10 text-emerald border border-emerald/30">
              Plant 04 - Bangalore, Karnataka
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Enterprise decision intelligence, P&amp;L revenue protection, and autonomous policy simulation.
          </p>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-dark-900/60 border border-border-subtle">
            <StatusPulse status={kpiDataError ? "critical" : "healthy"} label={kpiDataError ? "System Status: NO DATA" : "System Status: OPTIMAL"} />
          </div>
        </div>
      </div>

      {kpiDataLoading && <p className="text-sm text-text-secondary">Loading enterprise intelligence…</p>}
      {kpiDataError && <p className="text-sm text-status-red">Could not load enterprise intelligence (check token).</p>}

      {/* KPI Cards Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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

      {/* What-If Autonomy Simulator & Risk Signals Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* What-If Autonomy Simulator */}
        <div className="lg:col-span-7 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">📈</span>
              <h2 className="text-lg font-semibold text-text-primary">What-If Autonomy Simulator</h2>
            </div>
            <span className="text-xs font-mono text-cobalt px-2.5 py-1 rounded bg-cobalt/10 border border-cobalt/20">
              Live Policy Simulator
            </span>
          </div>

          <p className="text-xs text-text-secondary">
            Simulate the operational and financial outcome of recalibrating causal thresholds across failure conditions.
          </p>

          {/* Condition Selector Tabs */}
          <div className="flex flex-wrap gap-2 pt-2">
            {[
              { id: "COND-TOL-DRIFT", label: "Tolerance Drift" },
              { id: "COND-HUMIDITY-SPIKE", label: "Humidity Spike" },
              { id: "COND-SPINDLE-VIB", label: "Spindle Vibration" },
              { id: "COND-MATERIAL-DEFECT", label: "Material Inclusion" },
            ].map((cond) => (
              <button
                key={cond.id}
                onClick={() => setSelectedCondition(cond.id)}
                className={`px-3 py-1.5 text-xs font-mono rounded-lg transition-all border ${
                  selectedCondition === cond.id
                    ? "bg-cobalt/20 text-text-primary border-cobalt"
                    : "bg-dark-900/40 text-text-secondary border-border-subtle hover:border-border-accent"
                }`}
              >
                {cond.label}
              </button>
            ))}
          </div>

          {/* Simulation Output Display */}
          <div className="mt-4 p-4 rounded-lg bg-dark-900/60 border border-border-subtle space-y-3">
            <div className="flex justify-between items-center text-xs font-mono">
              <span className="text-text-secondary">Simulated Target Condition:</span>
              <span className="text-mono font-medium">{selectedCondition}</span>
            </div>

            {whatIfQuery.isLoading && <div className="text-xs text-text-secondary">Simulating…</div>}
            {whatIfQuery.isError && <div className="text-xs text-status-red">Could not run simulation (check token).</div>}

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-2">
              <div className="p-3 rounded bg-card/40 border border-border-subtle">
                <div className="text-xs text-text-secondary">Projected MTTR</div>
                <div className="text-lg font-mono font-bold text-emerald">
                  {whatIf ? `${whatIf.simulated.mttr_avg_min.toFixed(1)}m` : "—"}
                </div>
              </div>

              <div className="p-3 rounded bg-card/40 border border-border-subtle">
                <div className="text-xs text-text-secondary">Projected Revenue Prot.</div>
                <div className="text-lg font-mono font-bold text-emerald">{formatUsd(whatIf?.simulated.revenue_protected_usd)}</div>
              </div>

              <div className="p-3 rounded bg-card/40 border border-border-subtle col-span-2 sm:col-span-1">
                <div className="text-xs text-text-secondary">Projected Autonomy %</div>
                <div className="text-lg font-mono font-bold text-purple">{formatPct(whatIf?.simulated.autonomy_index)}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Predictive Risk Radar */}
        <div className="lg:col-span-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🛡️</span>
              <h2 className="text-lg font-semibold text-text-primary">Predictive Risk Radar</h2>
            </div>
            <span className="text-xs font-mono text-amber px-2 py-0.5 rounded bg-amber/10 border border-amber/20">
              {risks.length} Signals
            </span>
          </div>

          <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
            {riskQuery.isLoading ? (
              <div className="text-xs text-text-secondary py-6 text-center">Loading risk signals…</div>
            ) : riskQuery.isError ? (
              <div className="text-xs text-status-red py-6 text-center">Could not load risk signals (check token).</div>
            ) : risks.length === 0 ? (
              <div className="text-xs text-text-secondary py-6 text-center">No active risk signals detected.</div>
            ) : (
              risks.map((risk) => (
                <div key={risk.signalId} className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle space-y-1">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-text-primary font-semibold">{risk.lineId}</span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        risk.risk_level === "CRITICAL"
                          ? "bg-red/20 text-red border border-red/40"
                          : risk.risk_level === "ELEVATED"
                          ? "bg-amber/20 text-amber border border-amber/40"
                          : "bg-emerald/20 text-emerald border border-emerald/40"
                      }`}
                    >
                      {risk.risk_level} ({(risk.risk_score * 100).toFixed(0)}%)
                    </span>
                  </div>
                  <div className="text-xs text-text-secondary">{risk.primaryRiskDriver}</div>
                  <div className="text-[11px] font-mono text-mono pt-1">
                    Mitigation: {risk.recommendedMitigation}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Strategic Recommendations */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">💡</span>
            <h2 className="text-lg font-semibold text-text-primary">Strategic Recommendations</h2>
          </div>
          <span className="text-xs font-mono text-emerald px-2.5 py-1 rounded bg-emerald/10 border border-emerald/20">
            {recs.length} Recommendations Generated
          </span>
        </div>

        {recsQuery.isLoading && <p className="text-xs text-text-secondary">Loading recommendations…</p>}
        {recsQuery.isError && <p className="text-xs text-status-red">Could not load recommendations (check token).</p>}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {recs.map((rec) => (
            <div key={rec.recommendationId} className="p-4 rounded-lg bg-dark-900/60 border border-border-subtle space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cobalt/20 text-cobalt border border-cobalt/30">
                  {rec.category}
                </span>
                <span className="text-xs font-mono text-emerald font-semibold">
                  +${rec.estimatedAnnualSavingsUsd?.toLocaleString()} / yr
                </span>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">{rec.title}</h3>
              <p className="text-xs text-text-secondary">{rec.summary}</p>
              {rec.actionItems && rec.actionItems.length > 0 && (
                <div className="pt-2">
                  <div className="text-[11px] font-mono text-text-secondary mb-1">Action Plan:</div>
                  <ul className="list-disc list-inside text-xs text-text-primary space-y-0.5">
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
