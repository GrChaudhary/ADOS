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
import { MOTOR_HOUSING_QUALITY_ALERT } from "@/lib/demoScenario";

export default function DigitalTwinPage() {
  const router = useRouter();
  const { recentIncidents, activeIncidentLines, addIncident } = useMissionControlStore();
  const [starting, setStarting] = useState(false);
  const [qualityAlert, setQualityAlert] = useState<{ incidentId: string; lineId: string } | null>(null);
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
  const revenueProtected = kpisQuery.data ? `$${Math.round(kpisQuery.data.revenueProtectedUsd).toLocaleString()}` : "—";
  const openIncidents = recentIncidents.filter((i) => i.status === "in_progress").length;

  async function simulateQualityAlert() {
    setStarting(true);
    try {
      const result = await api.startIncident(MOTOR_HOUSING_QUALITY_ALERT);
      addIncident(result.incident_id, MOTOR_HOUSING_QUALITY_ALERT.line_id);
      setQualityAlert({ incidentId: result.incident_id, lineId: MOTOR_HOUSING_QUALITY_ALERT.line_id });
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
            return (
              <div key={line.lineId} className="rounded-md border border-border-subtle bg-glass px-4 py-2">
                <StatusPulse status={status === "OPERATIONAL" ? "healthy" : "critical"} label={line.lineId} />
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border-subtle bg-card p-6">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">Quality Inspection</h2>
          <p className="mt-1 text-sm text-text-secondary">
            Simulate Emma uploading a failed inspection on the Motor Housing line.
          </p>
        </div>
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
