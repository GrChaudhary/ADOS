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
    <div className="flex flex-col gap-6">
      <div className="text-center">
        <h1 className="text-2xl font-bold">Nova Motors — Production Command Center</h1>
        <p className="mt-1 text-sm text-text-secondary">When a factory doesn&apos;t know what to do next, ADOS does.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Production Health" value={productionHealth} />
        <KpiCard label="Open Incidents" value={String(openIncidents)} accentColor={openIncidents > 0 ? "status-red" : "emerald"} />
        <KpiCard label="Autonomous Decisions" value={String(autonomousDecisions)} accentColor="purple" />
        <KpiCard label="Revenue Protected" value={revenueProtected} accentColor="cobalt" />
      </div>

      <div className="rounded-lg border border-border-subtle bg-card p-6">
        <h2 className="mb-4 text-sm font-semibold text-text-secondary">Live Digital Twin</h2>
        {linesQuery.isLoading && <p className="text-sm text-text-secondary">Loading production lines…</p>}
        {linesQuery.isError && <p className="text-sm text-status-red">Could not load digital twin (check token).</p>}
        <div className="flex flex-wrap gap-4">
          {linesQuery.data?.map((line) => {
            const overridden = activeIncidentLines.has(line.lineId);
            const status = overridden ? "DEGRADED" : line.status;
            const readings = Object.entries(line.telemetry)
              .filter((entry): entry is [string, number] => entry[0] !== "last_reading_time" && typeof entry[1] === "number")
              .slice(0, 2);
            return (
              <div key={line.lineId} className="rounded-md border border-border-subtle bg-glass px-4 py-2">
                <StatusPulse status={status === "OPERATIONAL" ? "healthy" : "critical"} label={line.lineId} />
                {readings.length > 0 && (
                  <div className="mt-1 flex flex-col gap-0.5">
                    {readings.map(([key, value]) => (
                      <span key={key} className="text-xs text-text-secondary">
                        {formatTelemetryLabel(key)}: {value}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border-subtle bg-card p-6">
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

      <div className="rounded-lg border border-border-subtle bg-card p-6">
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="max-w-sm rounded-xl border border-status-red bg-card p-6 text-center">
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
