"use client";

// Incident Workspace - documentation/01_Product_Design_Specification.md
// Screen 3. Ports frontend/demo.js's workspace logic directly - same
// interaction model (tabs, SSE backfill-then-live dedupe, Option A/B/C
// cards, approval, live execution checklist, recovery banner), translated
// to React/TanStack Query.

import { use, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { OptionCard } from "@/components/design-system/OptionCard";
import { api, openIncidentEventStream, type EventEnvelope, type IncidentOption, type IncidentRecord } from "@/lib/api";
import { resolveAgentMeta } from "@/lib/agents";
import { useMissionControlStore } from "@/lib/store";

type TabName = "overview" | "evidence" | "reasoning" | "recommendations" | "execution" | "audit";
const TABS: TabName[] = ["overview", "evidence", "reasoning", "recommendations", "execution", "audit"];

interface ChecklistState {
  capability: string;
  steps: string[];
  phase: "started" | "completed";
  succeeded?: boolean;
}

export default function IncidentWorkspacePage(props: PageProps<"/incidents/[incidentId]">) {
  const { incidentId } = use(props.params);
  // Keyed by incidentId: navigating between two different incidents fully
  // remounts IncidentWorkspaceContent, which resets all its local state for
  // free (React's recommended pattern - see "You Might Not Need an Effect")
  // instead of manually clearing each piece of state inside an effect.
  return <IncidentWorkspaceContent key={incidentId} incidentId={incidentId} />;
}

function IncidentWorkspaceContent({ incidentId }: { incidentId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const setIncidentStatus = useMissionControlStore((s) => s.setIncidentStatus);

  const [activeTab, setActiveTab] = useState<TabName>("overview");
  const [approving, setApproving] = useState(false);
  const [visionResult, setVisionResult] = useState<Record<string, unknown> | null>(null);
  const [cadResult, setCadResult] = useState<Record<string, unknown> | null>(null);
  const [reasoningResult, setReasoningResult] = useState<Record<string, unknown> | null>(null);
  const [liveOptions, setLiveOptions] = useState<IncidentOption[] | null>(null);
  const [checklist, setChecklist] = useState<ChecklistState | null>(null);
  const [auditLog, setAuditLog] = useState<EventEnvelope[]>([]);
  const seenEventIds = useRef<Set<string>>(new Set());

  const incidentQuery = useQuery({
    queryKey: ["incident", incidentId],
    queryFn: () => api.getIncident(incidentId),
    refetchInterval: (query) => {
      const data = query.state.data as IncidentRecord | undefined;
      return data?.finalState ? false : 1000;
    },
  });

  const record = incidentQuery.data;
  const isResolved = record && "finalState" in record;
  const finalState = isResolved ? (record as IncidentRecord).finalState : undefined;
  const awaitingApproval = record && "awaitingApproval" in record && record.awaitingApproval;

  // Historical/authoritative comparison once resolved (in case SSE missed
  // anything, though it should already have it live from the
  // impact-simulation-agent's AgentCompleted event below).
  const optionsQuery = useQuery({
    queryKey: ["incident-options", incidentId],
    queryFn: () => api.getIncidentOptions(incidentId),
    enabled: Boolean(finalState),
  });

  useEffect(() => {
    if (finalState) {
      setIncidentStatus(incidentId, finalState);
    }
  }, [finalState, incidentId, setIncidentStatus]);

  useEffect(() => {
    function handleEvent(envelope: EventEnvelope) {
      if (envelope.incidentId !== incidentId) return;
      if (seenEventIds.current.has(envelope.eventId)) return;
      seenEventIds.current.add(envelope.eventId);

      setAuditLog((prev) => [envelope, ...prev]);

      const payload = envelope.payload as {
        agentId?: string;
        agent_id?: string;
        result?: Record<string, unknown>;
        capability?: string;
        executionSteps?: string[];
        status?: string;
      };
      const agentId = payload.agentId ?? payload.agent_id ?? "";

      if (envelope.eventType === "AgentCompleted") {
        if (agentId.includes("vision-spec")) setVisionResult(payload.result ?? null);
        else if (agentId.includes("cad-spec")) setCadResult(payload.result ?? null);
        else if (agentId.includes("causal-isolation")) setReasoningResult(payload.result ?? null);
        else if (agentId.includes("impact-simulation")) {
          const rankedOptions = payload.result?.ranked_options as
            | Array<Record<string, unknown>>
            | undefined;
          if (rankedOptions?.length) {
            setLiveOptions(
              rankedOptions.map((o, idx) => ({
                letter: String.fromCharCode(65 + idx),
                optionId: String(o.option_id ?? `OPT-${idx + 1}`),
                name: String(o.name ?? "Option"),
                estimatedCostUsd: Number(o.estimated_cost_usd ?? 0),
                downtimeMinutes: Number(o.downtime_minutes ?? 0),
                qualityRiskScore: Number(o.quality_risk_score ?? 0),
                overallScore: Number(o.overall_score ?? 0),
                recommendation: (o.recommendation as IncidentOption["recommendation"]) ?? "FEASIBLE",
                savingsUsd: 0, // recomputed below once the full set is known
                starRating: Math.max(1, Math.min(5, Math.round(Number(o.overall_score ?? 0) * 5))),
                isRecommended: o.recommendation === "TOP_PICK",
              }))
            );
          }
        }
      } else if (envelope.eventType === "CapabilityInvocationStarted") {
        setChecklist({ capability: payload.capability ?? "Capability", steps: payload.executionSteps ?? [], phase: "started" });
      } else if (envelope.eventType === "CapabilityInvocationCompleted") {
        setChecklist({
          capability: payload.capability ?? "Capability",
          steps: payload.executionSteps ?? [],
          phase: "completed",
          succeeded: payload.status === "succeeded",
        });
      }
    }

    // Open the live stream FIRST, then backfill anything that already
    // fired before we subscribed (event_bus.stream() has no replay - a
    // fast-resolving incident can complete every stage before this
    // component even finishes mounting). Opening SSE first means the
    // backfill can only ever double-report an event (harmless, deduped by
    // eventId above), never lose one to the gap between the two calls.
    const es = openIncidentEventStream(incidentId, handleEvent);
    api.listIncidentEvents(incidentId).then((events) => events.forEach(handleEvent)).catch(console.error);

    return () => es.close();
  }, [incidentId]);

  // liveOptions (from the SSE-streamed impact-simulation event) is the
  // primary source for an in-flight incident; optionsQuery.data (the REST
  // endpoint, only enabled once resolved) is the fallback for revisiting an
  // already-resolved incident where no SSE events will ever arrive again.
  const rawOptions = liveOptions ?? optionsQuery.data?.options ?? null;

  // Recompute savings-vs-costliest once the option set is known, same math
  // as executive/recommendation_comparison.py.
  const optionsWithSavings = rawOptions
    ? (() => {
        const maxCost = Math.max(...rawOptions.map((o) => o.estimatedCostUsd));
        return rawOptions.map((o) => ({ ...o, savingsUsd: Math.max(0, maxCost - o.estimatedCostUsd) }));
      })()
    : null;

  async function approve() {
    setApproving(true);
    try {
      await api.approveIncident(incidentId, "Emma Rodriguez (Quality Engineer)");
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
    } catch (e) {
      window.alert(`Approval failed: ${(e as Error).message}`);
    } finally {
      setApproving(false);
    }
  }

  const statusLabel = isResolved ? finalState : awaitingApproval ? "Awaiting Approval" : "In Progress";
  const statusClass = finalState === "Resolved" ? "text-emerald" : finalState === "Failed" ? "text-status-red" : "text-amber";

  return (
    <div className="flex flex-col gap-4">
      <button type="button" onClick={() => router.push("/digital-twin")} className="w-fit text-sm text-text-secondary hover:text-cobalt">
        ← Mission Control
      </button>

      {isResolved && finalState === "Resolved" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald bg-emerald/10 px-5 py-3">
          <span className="font-bold text-emerald">✓ Production Resumed</span>
          <div className="flex gap-4 text-sm">
            <span>
              <strong>{(record as IncidentRecord).actualDowntimeMin ?? "—"} min</strong> downtime
            </span>
            <span>
              <strong>{Math.round(((record as IncidentRecord).confidence ?? 0) * 100)}%</strong> confidence
            </span>
            <span>{["Tier 0 · Autonomous", "Tier 1 · Approved", "Tier 2 · Executive"][(record as IncidentRecord).policyTier] ?? ""}</span>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Motor Housing Incident — {incidentId.slice(0, 8)}</h1>
        <span className={`text-sm font-semibold ${statusClass}`}>{statusLabel}</span>
      </div>

      <div className="flex gap-1 border-b border-border-subtle">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-sm capitalize ${
              activeTab === tab ? "border-b-2 border-cobalt text-text-primary" : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-border-subtle bg-card p-5">
        {activeTab === "overview" && (
          <div className="space-y-2 text-sm">
            <Row k="Incident" v={incidentId} />
            <Row k="Status" v={statusLabel ?? "—"} />
            {isResolved && <Row k="Confidence" v={`${Math.round(((record as IncidentRecord).confidence ?? 0) * 100)}%`} />}
            {isResolved && (record as IncidentRecord).approvedBy && <Row k="Approved by" v={(record as IncidentRecord).approvedBy!} />}
          </div>
        )}

        {activeTab === "evidence" && (
          <div className="space-y-2 text-sm">
            {!visionResult && !cadResult && <Empty text="Waiting for Vision & CAD analysis…" />}
            {visionResult && (
              <>
                <Row k="Defect Detected" v={visionResult.defect_detected ? "Yes" : "No"} />
                <Row k="Measured Bore Diameter" v={`${visionResult.measured_value} mm`} />
                <Row k="Deviation" v={`${visionResult.deviation_mm} mm`} />
              </>
            )}
            {cadResult && (
              <>
                <Row k="Spec Violation" v={cadResult.is_violation ? `Yes (${cadResult.violation_direction})` : "No"} />
                <Row
                  k="Allowed Range"
                  v={`${(cadResult.tolerance_range as number[])?.[0] ?? "—"} – ${(cadResult.tolerance_range as number[])?.[1] ?? "—"} mm`}
                />
              </>
            )}
          </div>
        )}

        {activeTab === "reasoning" && (
          <div className="space-y-2 text-sm">
            {!reasoningResult && <Empty text="Waiting for root-cause analysis…" />}
            {reasoningResult && (
              <>
                <Row k="Primary Root Cause" v={String(reasoningResult.primary_root_cause ?? "—")} />
                {(reasoningResult.ranked_causes as Array<{ name: string; weight: number }> | undefined)?.map((c) => (
                  <Row key={c.name} k={c.name} v={`weight ${c.weight}`} />
                ))}
              </>
            )}
          </div>
        )}

        {activeTab === "recommendations" && (
          <div className="space-y-4">
            {!optionsWithSavings && <Empty text="Waiting for recommendation options…" />}
            {optionsWithSavings && (
              <>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {optionsWithSavings.map((o) => (
                    <OptionCard key={o.optionId} option={o} onApprove={awaitingApproval ? approve : undefined} approving={approving} />
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {activeTab === "execution" && (
          <div className="space-y-2 text-sm">
            {!checklist && <Empty text="Nothing executing yet." />}
            {checklist && (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-semibold">{checklist.capability}</span>
                  <span className={checklist.phase === "started" ? "text-amber" : checklist.succeeded ? "text-emerald" : "text-status-red"}>
                    {checklist.phase === "started" ? "In Progress" : checklist.succeeded ? "Completed" : "Failed"}
                  </span>
                </div>
                {checklist.steps.map((step) => (
                  <div key={step} className="flex items-center gap-2 py-1">
                    <span className={checklist.phase === "started" ? "text-amber" : checklist.succeeded ? "text-emerald" : "text-status-red"}>
                      {checklist.phase === "started" ? "●" : checklist.succeeded ? "✓" : "✗"}
                    </span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === "audit" && (
          <div className="space-y-2">
            {auditLog.length === 0 && <Empty text="No events recorded yet." />}
            {auditLog.map((e) => {
              const payload = e.payload as { agentId?: string; agent_id?: string };
              const agentId = payload.agentId ?? payload.agent_id;
              const meta = agentId ? resolveAgentMeta(agentId) : null;
              return (
                <div key={e.eventId} className="flex items-center justify-between rounded-md border border-border-subtle bg-glass px-3 py-2 text-xs">
                  <span>
                    {meta && <span className="mr-1">{meta.icon}</span>}
                    {e.eventType}
                  </span>
                  <span className="text-text-secondary">{e.occurredAt}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between border-b border-border-subtle py-1.5 last:border-none">
      <span className="text-text-secondary">{k}</span>
      <span>{v}</span>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm italic text-text-secondary">{text}</p>;
}
