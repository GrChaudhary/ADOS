"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, clearSession, DecisionMemorySearchResult, IncidentRecord } from "@/lib/api";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { useHasToken } from "@/lib/useHasToken";

interface DecisionItem {
  id: string;
  incidentId: string;
  plantId: string;
  lineId: string;
  defectType: string;
  selectedOption: string;
  savingsUsd: number;
  exposureUsd: number;
  downtimeMin: number;
  status: "AWAITING_APPROVAL" | "TIER0_AUTONOMOUS" | "APPROVED" | "REJECTED";
  approvedBy: string | null;
  timestamp: string;
}

export default function DecisionsPage() {
  const hasToken = useHasToken();
  const currentUser = useCurrentUser();
  const [activeFilter, setActiveFilter] = useState<string>("ALL");
  const [localApprovals, setLocalApprovals] = useState<Record<string, boolean>>({});

  // Query real Decision Memory historical and active incident audit records from backend
  const memoryQuery = useQuery<DecisionMemorySearchResult>({
    queryKey: ["decisions-memory-search"],
    queryFn: () => api.searchDecisionMemory({ limit: 100 }),
    refetchInterval: 5000,
    enabled: hasToken,
  });

  const liveRecords = memoryQuery.data?.records ?? [];

  // Map real FastAPI backend IncidentRecord models to DecisionItem table rows
  const realDecisions: DecisionItem[] = liveRecords.map((rec: IncidentRecord) => {
    const isTier0 = rec.policyTier === 0;
    const isLocalApproved = localApprovals[rec.incidentId];
    const isBackendApproved = rec.recommendationAccepted === true;

    let status: DecisionItem["status"] = "AWAITING_APPROVAL";
    if (isTier0) {
      status = "TIER0_AUTONOMOUS";
    } else if (isLocalApproved || isBackendApproved) {
      status = "APPROVED";
    } else if (rec.recommendationAccepted === false) {
      status = "REJECTED";
    }

    return {
      id: `dec-${rec.incidentId}`,
      incidentId: rec.incidentId,
      plantId: rec.plantId ?? "PLANT-04-BANGALORE",
      lineId: rec.lineId ?? "Line 2",
      defectType: (rec.causalChain?.[0]?.conditionId ?? "BORE_TOLERANCE_EXCEEDED").replace("COND-", ""),
      selectedOption: rec.capabilityInvoked
        ? `Execute ${rec.capabilityInvoked}`
        : "Option A (Switch Supplier to PrecisionCast GmbH + Recalibrate)",
      savingsUsd: Math.max(0, (rec.estimatedCostUsd ?? 430000) - (rec.actualCostUsd ?? 15000)),
      exposureUsd: rec.estimatedCostUsd ?? 0,
      downtimeMin: rec.actualDowntimeMin ?? rec.estimatedDowntimeMin ?? 6,
      status: status,
      approvedBy: rec.approvedBy ?? (isTier0 ? "Tier 0 Autonomy Policy Engine" : isLocalApproved && currentUser ? `${currentUser.displayName} (${currentUser.role})` : null),
      timestamp: rec.createdAt ? new Date(rec.createdAt).toLocaleTimeString() : "Just now",
    };
  });

  // The logged-in user's approvalLimitUsd is checked here for a responsive
  // UI (grey out what would 403 anyway), but the backend
  // (backend/app/routers/incidents.py's _authorize_decision) is the real
  // enforcement point - this is a hint, not the security boundary.
  const canApprove = (exposureUsd: number) =>
    Boolean(currentUser) && currentUser!.approvalLimitUsd > 0 && exposureUsd <= currentUser!.approvalLimitUsd;

  const handleApprove = (incidentId: string) => {
    setLocalApprovals((prev) => ({ ...prev, [incidentId]: true }));
    api.approveIncident(incidentId).catch((err) => {
      console.error("Failed to approve incident on backend", err);
    });
  };

  const handleBulkApprove = () => {
    realDecisions.forEach((d) => {
      if (d.status === "AWAITING_APPROVAL" && canApprove(d.exposureUsd)) {
        handleApprove(d.incidentId);
      }
    });
  };

  const filteredDecisions = realDecisions.filter((d) => {
    if (activeFilter === "ALL") return true;
    if (activeFilter === "AWAITING_APPROVAL") return d.status === "AWAITING_APPROVAL";
    if (activeFilter === "TIER0") return d.status === "TIER0_AUTONOMOUS";
    if (activeFilter === "APPROVED") return d.status === "APPROVED";
    if (activeFilter === "REJECTED") return d.status === "REJECTED";
    return true;
  });

  const pendingCount = realDecisions.filter((d) => d.status === "AWAITING_APPROVAL").length;
  const approvableCount = realDecisions.filter((d) => d.status === "AWAITING_APPROVAL" && canApprove(d.exposureUsd)).length;

  return (
    <div className="space-y-8 pb-12">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Global Decision Center</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-cobalt/10 text-cobalt border border-cobalt/30">
              Live FastAPI Backend Wiring
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Cross-incident recommendation command center reading real <code className="text-emerald">IncidentRecord</code> audit trails from Decision Memory.
          </p>
          <p className="text-xs font-mono text-text-secondary mt-1">
            {currentUser ? (
              <>
                Approving as <span className="text-cobalt font-semibold">{currentUser.displayName}</span> —{" "}
                {currentUser.approvalLimitUsd > 0 ? `up to $${currentUser.approvalLimitUsd.toLocaleString("en-US")}` : "read-only, no approval authority"}{" "}
                (
                <button onClick={() => { clearSession(); window.location.href = "/login"; }} className="underline hover:text-text-primary">
                  log out
                </button>
                )
              </>
            ) : (
              <a href="/login" className="underline hover:text-text-primary">Log in to approve decisions</a>
            )}
          </p>
        </div>

        {/* Bulk Actions */}
        {approvableCount > 0 && (
          <button
            onClick={handleBulkApprove}
            className="px-4 py-2 rounded-lg bg-emerald text-white font-mono text-xs font-bold hover:bg-emerald/80 transition-all border border-emerald/40 shadow-lg"
          >
            ⚡ Bulk Approve Within Limit ({approvableCount})
          </button>
        )}
      </div>

      {!hasToken && <p className="text-sm text-text-secondary">Enter a service token to load Decision Memory.</p>}
      {hasToken && memoryQuery.isLoading && <p className="text-sm text-text-secondary">Loading decision records…</p>}
      {hasToken && memoryQuery.isError && (
        <p className="text-sm text-status-red">Could not load Decision Memory (check token).</p>
      )}

      {/* Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2 p-2 rounded-2xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl font-mono text-xs shadow-lg">
        {[
          { id: "ALL", label: `All Decisions (${realDecisions.length})` },
          { id: "AWAITING_APPROVAL", label: `Awaiting Approval (${pendingCount})` },
          { id: "TIER0", label: "Tier 0 Autonomous" },
          { id: "APPROVED", label: "Approved" },
          { id: "REJECTED", label: "Rejected" },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveFilter(tab.id)}
            className={`px-3 py-1.5 rounded-lg transition-all ${
              activeFilter === tab.id
                ? "bg-cobalt text-white font-semibold shadow"
                : "text-text-secondary hover:text-text-primary hover:bg-glass"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Cross-Incident Decision Table */}
      <div className="rounded-3xl jarvis-static-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚖️</span>
            <h2 className="text-lg font-semibold text-text-primary">Enterprise Decision Recommendations</h2>
          </div>
          <span className="text-xs font-mono text-text-secondary">
            Showing {filteredDecisions.length} Decisions from Decision Memory
          </span>
        </div>

        {filteredDecisions.length === 0 ? (
          <div className="text-xs font-mono text-text-secondary py-12 text-center">
            No decisions match the selected filter.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-border-subtle text-text-secondary">
                  <th className="py-3 px-3">INCIDENT</th>
                  <th className="py-3 px-3">LINE</th>
                  <th className="py-3 px-3">DEFECT TYPE</th>
                  <th className="py-3 px-3">SELECTED OPTION</th>
                  <th className="py-3 px-3">SAVINGS</th>
                  <th className="py-3 px-3">STATUS</th>
                  <th className="py-3 px-3">ACTION</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle text-text-primary">
                {filteredDecisions.map((d) => (
                  <tr key={d.id} className="hover:bg-glass transition-all">
                    <td className="py-3.5 px-3 font-bold text-cobalt">{d.incidentId}</td>
                    <td className="py-3.5 px-3">{d.lineId}</td>
                    <td className="py-3.5 px-3 text-text-secondary">{d.defectType}</td>
                    <td className="py-3.5 px-3 text-text-primary font-medium max-w-xs truncate">{d.selectedOption}</td>
                    <td className="py-3.5 px-3 text-emerald font-bold">+${d.savingsUsd.toLocaleString()}</td>
                    <td className="py-3.5 px-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          d.status === "AWAITING_APPROVAL"
                            ? "bg-amber/20 text-amber border border-amber/40"
                            : d.status === "TIER0_AUTONOMOUS"
                            ? "bg-purple/20 text-purple border border-purple/40"
                            : d.status === "APPROVED"
                            ? "bg-emerald/20 text-emerald border border-emerald/40"
                            : "bg-status-red/20 text-status-red border border-status-red/40"
                        }`}
                      >
                        {d.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="py-3.5 px-3">
                      {d.status === "AWAITING_APPROVAL" ? (
                        canApprove(d.exposureUsd) ? (
                          <button
                            onClick={() => handleApprove(d.incidentId)}
                            className="px-3 py-1 rounded bg-emerald text-white text-[11px] font-semibold hover:bg-emerald/80 transition-all shadow"
                          >
                            Approve
                          </button>
                        ) : (
                          <span
                            className="text-[11px] text-status-red"
                            title={currentUser ? `Exceeds ${currentUser.displayName}'s $${currentUser.approvalLimitUsd.toLocaleString("en-US")} approval limit` : "Log in to approve"}
                          >
                            Exceeds your limit
                          </span>
                        )
                      ) : (
                        <span className="text-[11px] text-text-secondary">{d.approvedBy ?? "Completed"}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
