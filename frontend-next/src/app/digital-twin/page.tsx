"use client";

// Mission Control / Operational Plant Control Room (Digital Twin) -
// documentation/01_Product_Design_Specification.md Screen 2. Ports the
// verified behavior from frontend/demo.js's home screen directly - same
// interaction model, translated to React/TanStack Query/Zustand.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { KpiCard } from "@/components/design-system/KpiCard";
import { StatusPulse } from "@/components/design-system/StatusPulse";
import { api } from "@/lib/api";
import { useMissionControlStore } from "@/lib/store";
import { useHasToken } from "@/lib/useHasToken";
import { QUALITY_ALERT_SCENARIOS } from "@/lib/demoScenario";
import studioStyles from "../novus-studio/studio.module.css";

// "vibration_rms_mm_s" -> "Vibration Rms Mm S" — good enough for a compact
// live-telemetry readout without needing a per-key label/unit lookup table.
function formatTelemetryLabel(key: string): string {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function DigitalTwinPage() {
  const router = useRouter();
  const { recentIncidents, activeIncidentLines, addIncident } = useMissionControlStore();
  const [starting, setStarting] = useState(false);
  const [qualityAlert, setQualityAlert] = useState<{ incidentId: string; lineId: string } | null>(null);
  const [selectedScenarioLineId, setSelectedScenarioLineId] = useState("Line 2"); // hero scenario
  const hasToken = useHasToken();

  const kpisQuery = useQuery({ queryKey: ["kpis"], queryFn: api.getKpis, enabled: hasToken });
  const linesQuery = useQuery({
    queryKey: ["digital-twin-lines"],
    queryFn: api.getDigitalTwinLines,
    refetchInterval: 5000,
    enabled: hasToken,
  });

  const busy = recentIncidents.some((i) => i.status === "in_progress");

  const productionHealth =
    kpisQuery.data && kpisQuery.data.totalIncidents > 0
      ? `${Math.round((kpisQuery.data.resolvedIncidents / kpisQuery.data.totalIncidents) * 100)}%`
      : "100%";
  const autonomousDecisions = kpisQuery.data?.tierDistribution?.["Tier 0 (Autonomous)"] ?? 0;
  const revenueProtected = kpisQuery.data ? `$${Math.round(kpisQuery.data.revenueProtectedUsd).toLocaleString("en-US")}` : "—";
  const openIncidents = recentIncidents.filter((i) => i.status === "in_progress").length;

  async function simulateQualityAlert() {
    const scenario = QUALITY_ALERT_SCENARIOS.find((s) => s.lineId === selectedScenarioLineId);
    if (!scenario) return;
    setStarting(true);
    try {
      const result = await api.startIncident(scenario.request);
      addIncident(result.incident_id, scenario.lineId);
      setQualityAlert({ incidentId: result.incident_id, lineId: scenario.lineId });
    } catch (e) {
      window.alert(`Could not start incident: ${(e as Error).message}`);
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="space-y-8 pb-12">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-orbitron font-extrabold text-white tracking-wide">
              Nova Motors — Production Command Center
            </h1>
            <span className="px-3 py-1 rounded-full text-xs font-mono bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-[0_0_12px_rgba(16,185,129,0.3)]">
              Digital Twin Active
            </span>
          </div>
          <p className="text-xs sm:text-sm text-purple-200/70 mt-2 font-sans">
            When a factory doesn&apos;t know what to do next, ADOS does.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Production Health" value={productionHealth} />
        <KpiCard label="Open Incidents" value={String(openIncidents)} accentColor={openIncidents > 0 ? "status-red" : "emerald"} />
        <KpiCard label="Autonomous Decisions" value={String(autonomousDecisions)} accentColor="purple" />
        <KpiCard label="Revenue Protected" value={revenueProtected} accentColor="cobalt" />
      </div>

      <div className="rounded-3xl jarvis-static-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <h2 className="mb-4 text-sm font-semibold text-text-secondary">Live Digital Twin</h2>
        {linesQuery.isLoading && <p className="text-sm text-text-secondary">Loading production lines…</p>}
        {linesQuery.isError && <p className="text-sm text-status-red">Could not load digital twin (check token).</p>}
        <div
          className={studioStyles.twinGrid}
          style={{
            ["--bg-raised" as any]: "var(--bg-glass)",
            ["--line" as any]: "var(--border-subtle)",
            ["--border-hover" as any]: "#38bdf8",
            ["--shadow-hover" as any]: "0 0 20px rgba(56, 189, 248, 0.45)",
            ["--muted" as any]: "var(--text-secondary)",
            ["--paper" as any]: "var(--text-primary)",
            ["--accent-cyan" as any]: "#00f0ff",
            ["--accent-lime" as any]: "#d7ff3e",
            ["--accent-orange" as any]: "#ff4b1f",
            ["--font-mono" as any]: "var(--font-jetbrains-mono), monospace",
            ["--font-display" as any]: "var(--font-orbitron), sans-serif",
          }}
        >
          {linesQuery.data?.map((line) => {
            const overridden = activeIncidentLines.has(line.lineId);
            const status = overridden ? "DEGRADED" : line.status;
            const readings = Object.entries(line.telemetry)
              .filter((entry): entry is [string, number] => entry[0] !== "last_reading_time" && typeof entry[1] === "number")
              .slice(0, 2);

            const shorthandId = line.lineId === "Warehouse" ? "WH" : line.lineId.replace("Line ", "L");

            let statusLabel = "NORMAL";
            let statusColor = "#00f0ff";
            if (status === "DEGRADED") {
              statusLabel = "ANOMALY";
              statusColor = "#ff4b1f";
            } else if (status === "STOPPED") {
              statusLabel = "WARNING";
              statusColor = "#d7ff3e";
            }

            return (
              <div key={line.lineId} className={studioStyles.lineCard}>
                <div className={studioStyles.cardTop}>
                  <span className={studioStyles.lineId}>{shorthandId}</span>
                  <span
                    className={studioStyles.statusBadge}
                    style={{
                      color: statusColor,
                      borderColor: statusColor
                    }}
                  >
                    ● {statusLabel}
                  </span>
                </div>
                <h3 className="font-orbitron font-bold text-white mb-1" style={{ fontSize: "1.15rem" }}>
                  {line.lineId}
                </h3>
                <p className={studioStyles.partLabel} style={{ marginBottom: "1.2rem" }}>
                  Part / SKU: {line.activeProductSku || "None"}
                </p>
                <div className={studioStyles.telemetryMetrics}>
                  {readings.map(([key, value]) => (
                    <div key={key}>
                      <span>{formatTelemetryLabel(key)}</span>
                      <strong style={{ color: status === "DEGRADED" ? "#ff4b1f" : "inherit" }}>
                        {typeof value === "number" ? value.toFixed(2) : String(value)}
                      </strong>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 p-6 rounded-3xl jarvis-static-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">Quality Inspection</h2>
          <p className="mt-1 text-sm text-text-secondary">
            Simulate Emma uploading a failed inspection on the selected line.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={selectedScenarioLineId}
            onChange={(e) => setSelectedScenarioLineId(e.target.value)}
            disabled={busy || starting}
            className="rounded-md border border-border-subtle bg-glass px-3 py-2.5 text-sm text-text-primary disabled:opacity-50"
          >
            {QUALITY_ALERT_SCENARIOS.map((scenario) => (
              <option key={scenario.lineId} value={scenario.lineId}>
                {scenario.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={simulateQualityAlert}
            disabled={busy || starting}
            title={busy ? "An incident is already in progress — resolve or approve it first." : ""}
            className="rounded-md bg-cobalt px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {starting ? "Starting…" : "Simulate Quality Alert"}
          </button>
        </div>
      </div>

      <div className="rounded-3xl jarvis-static-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <h2 className="mb-4 text-sm font-semibold text-text-secondary">Recent Incidents</h2>
        {recentIncidents.length === 0 && <p className="text-sm text-text-secondary">No incidents yet this session.</p>}
        <div className="flex flex-col gap-2">
          {[...recentIncidents].reverse().map((inc) => (
            <button
              key={inc.incidentId}
              type="button"
              onClick={() => router.push(`/incidents/${inc.incidentId}`)}
              className="flex items-center justify-between rounded-md border border-border-subtle bg-glass px-4 py-2 text-left text-sm hover:border-border-accent"
            >
              <span>
                {inc.lineId} — {inc.incidentId.slice(0, 8)}
              </span>
              <span className="text-text-secondary">{inc.status}</span>
            </button>
          ))}
        </div>
      </div>

      {qualityAlert && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md">
          <div className="max-w-sm rounded-3xl jarvis-glass-card border border-status-red bg-[#0d0926]/95 p-6 text-center shadow-2xl animate-fade-in">
            <div className="text-lg font-bold text-status-red">⚠ Quality Alert — Motor Housing</div>
            <p className="mt-2 text-sm text-text-secondary">
              Tolerance exceeded on {qualityAlert.lineId}. ADOS has started an investigation.
            </p>
            <button
              type="button"
              onClick={() => {
                const incidentId = qualityAlert.incidentId;
                setQualityAlert(null);
                router.push(`/incidents/${incidentId}`);
              }}
              className="mt-4 rounded-md bg-cobalt px-4 py-2 text-sm font-semibold text-white"
            >
              View Incident
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
