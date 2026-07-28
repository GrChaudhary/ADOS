"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, IncidentRecord } from "@/lib/api";
import { useMissionControlStore } from "@/lib/store";
import { useHasToken } from "@/lib/useHasToken";
import { QUALITY_ALERT_SCENARIOS } from "@/lib/demoScenario";

const MOTOR_HOUSING_QUALITY_ALERT = QUALITY_ALERT_SCENARIOS.find((s) => s.lineId === "Line 2")!.request;

export default function IncidentsHubPage() {
  const router = useRouter();
  const hasToken = useHasToken();
  const { recentIncidents, addIncident } = useMissionControlStore();
  const [starting, setStarting] = useState(false);

  // Fetch real historical & hero incident records from backend Decision Memory RAG
  const incidentsQuery = useQuery({
    queryKey: ["incidents-hub-list"],
    queryFn: () => api.searchDecisionMemory({ limit: 50 }),
    refetchInterval: 5000,
    enabled: hasToken,
  });

  const backendRecords = incidentsQuery.data?.records ?? [];

  async function handleSimulateIncident() {
    setStarting(true);
    try {
      const res = await api.startIncident(MOTOR_HOUSING_QUALITY_ALERT);
      addIncident(res.incident_id, MOTOR_HOUSING_QUALITY_ALERT.line_id);
      router.push(`/incidents/${res.incident_id}`);
    } catch (e) {
      window.alert(`Could not trigger incident: ${(e as Error).message}`);
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Incident Workspace Hub</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-status-red/10 text-status-red border border-status-red/30">
              Multi-Agent Defect Workspace
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Real-time quality defect workspace, CAD spec overlays, causal graph root cause analysis, and 1-Click option approvals.
          </p>
        </div>

        <button
          type="button"
          onClick={handleSimulateIncident}
          disabled={starting}
          className="px-4 py-2.5 rounded-lg bg-cobalt hover:bg-cobalt/90 text-white text-xs font-semibold shadow-md transition-all disabled:opacity-50 flex items-center gap-2"
        >
          <span>⚡</span>
          <span>{starting ? "Triggering..." : "Simulate New Quality Incident"}</span>
        </button>
      </div>

      {/* Hero Incidents Quick Selector */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">🚨</span>
            <h2 className="text-lg font-semibold text-text-primary">Active &amp; Demo Incident Tickets</h2>
          </div>
          <span className="text-xs font-mono text-text-secondary">
            {backendRecords.length} Tickets Found
          </span>
        </div>

        {incidentsQuery.isLoading && (
          <p className="text-sm text-text-secondary italic">Loading incident records from backend...</p>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 pt-2">
          {backendRecords.map((record: IncidentRecord) => {
            const isResolved = record.finalState === "Resolved";
            const tierLabel = ["Tier 0 (Autonomous)", "Tier 1 (Engineer Approval)", "Tier 2 (Executive Approval)"][record.policyTier] ?? "Tier 1";
            const cause = record.causalChain?.[0]?.description ?? "Bore tolerance drift detected";

            return (
              <div
                key={record.incidentId}
                className="p-5 rounded-xl bg-dark-900/60 border border-border-subtle hover:border-border-accent transition-all space-y-3 flex flex-col justify-between"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-cobalt">{record.incidentId}</span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[11px] font-mono border ${
                        isResolved
                          ? "bg-emerald/10 text-emerald border-emerald/30"
                          : "bg-amber/10 text-amber border-amber/30"
                      }`}
                    >
                      {record.finalState || "In Progress"}
                    </span>
                  </div>

                  <div className="text-xs font-semibold text-text-primary">
                    {record.lineId} · {record.plantId}
                  </div>

                  <p className="text-xs text-text-secondary line-clamp-2">{cause}</p>
                </div>

                <div className="space-y-3 pt-2 border-t border-border-subtle/60 text-xs font-mono">
                  <div className="flex justify-between text-text-secondary">
                    <span>Governance Tier:</span>
                    <span className="text-text-primary">{tierLabel}</span>
                  </div>

                  <div className="flex justify-between text-text-secondary">
                    <span>Confidence Score:</span>
                    <span className="text-emerald font-bold">{Math.round((record.confidence ?? 0) * 100)}%</span>
                  </div>

                  <button
                    type="button"
                    onClick={() => router.push(`/incidents/${record.incidentId}`)}
                    className="w-full py-2 rounded-lg bg-cobalt/10 hover:bg-cobalt/20 text-cobalt border border-cobalt/30 text-xs font-semibold transition-all flex items-center justify-center gap-1.5"
                  >
                    <span>Open Incident Workspace</span>
                    <span>→</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
