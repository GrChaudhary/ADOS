"use client";

// Incident Workspace - documentation/01_Product_Design_Specification.md
// Screen 3. Ports frontend/demo.js's workspace logic directly - same
// interaction model (tabs, SSE backfill-then-live dedupe, Option A/B/C
// cards, approval, live execution checklist, recovery banner), translated
// to React/TanStack Query.

import { use, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { OptionCard } from "@/components/design-system/OptionCard";
import { api, openIncidentEventStream, type EventEnvelope, type IncidentOption, type IncidentRecord } from "@/lib/api";
import { resolveAgentMeta } from "@/lib/agents";
import { useMissionControlStore } from "@/lib/store";
import { QUALITY_ALERT_SCENARIOS } from "@/lib/demoScenario";

type TabName = "overview" | "evidence" | "reasoning" | "recommendations" | "execution" | "audit";
const TABS: TabName[] = ["overview", "evidence", "reasoning", "recommendations", "execution", "audit"];

interface ChecklistState {
  capability: string;
  steps: string[];
  phase: "started" | "completed";
  succeeded?: boolean;
  connector?: string | null;
  output?: Record<string, unknown> | null;
  error?: string | null;
}

// Pipeline order the orchestrator actually runs stages in
// (orchestrate/orchestrator.py's run_incident) - drives the Execution tab's
// live timeline. Governance approval and capability dispatch aren't agents
// so they're spliced in separately, not listed here.
const PIPELINE_AGENT_IDS = [
  "vision-spec-agent",
  "cad-spec-agent",
  "causal-isolation-agent",
  "substitution-agent",
  "parameter-adjustment-agent",
  "impact-simulation-agent",
  "rerouting-agent",
] as const;
const LEARNING_AGENT_ID = "feedback-calibration-agent";

// Only these finalState values mean the incident is actually done
// (contracts/incident_state.py's IncidentState). Everything else —
// Detected/Diagnosing/CandidateGeneration/Reserving/AwaitingApproval/
// Executing — is still in flight, even though the Cloudant restart-
// recovery snapshot (backend/app/routers/incidents.py's _snapshot_pending)
// always carries a finalState key regardless of which of these it's at.
const TERMINAL_STATES = new Set(["Resolved", "Failed", "Escalated", "Preempted"]);

type StageStatus = "pending" | "running" | "done";

interface StageRow {
  agentId: string;
  status: StageStatus;
  requestedAt?: string;
  completedAt?: string;
  executionTimeMs?: number;
  confidence?: number;
  result?: Record<string, unknown>;
}

function eventAgentId(envelope: EventEnvelope): string {
  const payload = envelope.payload as { agentId?: string; agent_id?: string };
  return String(payload.agentId ?? payload.agent_id ?? envelope.producedBy ?? "").toLowerCase();
}

/** Derives a pending/running/done row per pipeline agent from the raw event
 * log, so the Execution tab reflects what's actually happening right now
 * instead of only lighting up during the final capability-dispatch window. */
function deriveStageRows(agentIds: readonly string[], auditLog: EventEnvelope[]): StageRow[] {
  return agentIds.map((agentId) => {
    // auditLog is newest-first (prepended in handleEvent)
    const completed = auditLog.find((e) => e.eventType === "AgentCompleted" && eventAgentId(e).includes(agentId.replace("-agent", "")));
    const requested = auditLog.find((e) => e.eventType === "StageRequested" && eventAgentId(e).includes(agentId.replace("-agent", "")));
    if (completed) {
      const payload = completed.payload as { executionTimeMs?: number; execution_time_ms?: number; confidence?: number; result?: Record<string, unknown> };
      return {
        agentId,
        status: "done" as const,
        requestedAt: requested?.occurredAt,
        completedAt: completed.occurredAt,
        executionTimeMs: payload.executionTimeMs ?? payload.execution_time_ms,
        confidence: payload.confidence,
        result: payload.result,
      };
    }
    if (requested) {
      return { agentId, status: "running" as const, requestedAt: requested.occurredAt };
    }
    return { agentId, status: "pending" as const };
  });
}

/** One human-readable line summarizing what a completed stage actually
 * found, pulled from that agent's real result shape (agents/*.py) rather
 * than a generic "done" label. */
function describeStageResult(agentId: string, result?: Record<string, unknown>): string | null {
  if (!result) return null;
  switch (agentId) {
    case "vision-spec-agent": {
      const dim = String(result.dimension ?? "measurement");
      const unit = String(result.unit ?? "mm");
      return result.defect_detected
        ? `Defect detected — ${dim}: ${result.measured_value}${unit} vs nominal ${result.nominal_target}${unit}`
        : `No defect — ${dim} within tolerance`;
    }
    case "cad-spec-agent":
      return result.is_violation
        ? `Spec violation (${result.violation_direction}) against ${result.spec_id ?? "governing spec"}`
        : `Within spec (${result.spec_id ?? "governing spec"})`;
    case "causal-isolation-agent":
      return `Primary cause: ${result.primary_root_cause} (${Math.round(Number(result.root_cause_confidence ?? 0) * 100)}% weight)`;
    case "substitution-agent": {
      const candidate = result.top_candidate as { target_part_number?: string } | null | undefined;
      return result.has_approved_substitute
        ? `Approved substitute found: ${candidate?.target_part_number}`
        : "No approved substitute registered for this part";
    }
    case "parameter-adjustment-agent":
      return `${result.parameter_to_adjust} → ${result.target_value}${result.unit} on ${result.line_id}`;
    case "impact-simulation-agent": {
      const top = result.top_recommendation as { name?: string; estimated_cost_usd?: number; downtime_minutes?: number } | undefined;
      return top ? `Top pick: ${top.name} ($${top.estimated_cost_usd}, ${top.downtime_minutes}min)` : null;
    }
    case "rerouting-agent": {
      const steps = result.execution_steps as unknown[] | undefined;
      return `${steps?.length ?? 0} execution step(s) planned for ${result.target_line_id}`;
    }
    case "feedback-calibration-agent":
      return "Causal graph edge weights recalibrated from this outcome";
    default:
      return null;
  }
}

const STAGE_LABELS: Record<StageStatus, string> = { pending: "Pending", running: "In Progress", done: "Complete" };
const STAGE_COLOR: Record<StageStatus, string> = {
  pending: "text-text-secondary",
  running: "text-amber animate-pulse",
  done: "text-emerald",
};
const STAGE_DOT: Record<StageStatus, string> = { pending: "○", running: "●", done: "✓" };

/** Turns one raw event envelope into an audit-log line a human can actually
 * read - what stage/agent it concerns and what it found, not just the
 * event type and producer string. */
function describeEvent(e: EventEnvelope): { icon?: string; title: string; detail?: string } {
  const payload = e.payload as {
    agentId?: string;
    agent_id?: string;
    stageName?: string;
    result?: Record<string, unknown>;
    confidence?: number;
    executionTimeMs?: number;
    execution_time_ms?: number;
    capability?: string;
    executionSteps?: string[];
    status?: string;
    connector?: string | null;
    error?: string | null;
  };
  const agentId = eventAgentId(e);
  const meta = agentId ? resolveAgentMeta(agentId) : null;

  if (e.eventType === "StageRequested") {
    return {
      icon: "▶",
      title: `${meta?.label ?? payload.stageName ?? "Stage"} started`,
      detail: meta ? `${meta.label} (${payload.stageName}) is now running.` : undefined,
    };
  }
  if (e.eventType === "AgentCompleted") {
    const ms = payload.executionTimeMs ?? payload.execution_time_ms;
    const summary = agentId ? describeStageResult(agentId, payload.result) : null;
    return {
      icon: meta?.icon ?? "✓",
      title: `${meta?.label ?? "Agent"} completed${ms !== undefined ? ` in ${ms}ms` : ""}`,
      detail:
        summary ??
        (payload.confidence !== undefined ? `Confidence ${Math.round(payload.confidence * 100)}%` : undefined),
    };
  }
  if (e.eventType === "CapabilityInvocationStarted") {
    return {
      icon: "⚙",
      title: `Dispatching ${payload.capability ?? "capability"}`,
      detail: payload.executionSteps ? `${payload.executionSteps.length} step(s) queued` : undefined,
    };
  }
  if (e.eventType === "CapabilityInvocationCompleted") {
    const ok = payload.status === "succeeded";
    return {
      icon: ok ? "✓" : "✗",
      title: `${payload.capability ?? "Capability"} ${ok ? "succeeded" : "failed"} via ${payload.connector ?? "connector"}`,
      detail: ok ? undefined : (payload.error ?? undefined),
    };
  }
  return { title: `${e.eventType} (${e.producedBy})` };
}

export default function IncidentWorkspacePage(props: PageProps<"/incidents/[incidentId]">) {
  const { incidentId } = use(props.params);
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

  const stageRows = useMemo(() => deriveStageRows(PIPELINE_AGENT_IDS, auditLog), [auditLog]);
  const learningRow = useMemo(() => deriveStageRows([LEARNING_AGENT_ID], auditLog)[0], [auditLog]);

  const incidentQuery = useQuery({
    queryKey: ["incident", incidentId],
    queryFn: () => api.getIncident(incidentId),
    refetchInterval: (query) => {
      const data = query.state.data as IncidentRecord | undefined;
      return data?.finalState && TERMINAL_STATES.has(data.finalState) ? false : 1000;
    },
  });

  const record = incidentQuery.data;
  // finalState reflects the raw value whenever the response carries the
  // key at all — both the live in-progress shape (never has this key) and
  // the Cloudant restart-recovery snapshot (always has it, but the value
  // is frequently a non-terminal state like "AwaitingApproval") carry it
  // differently. isResolved has to check the *value* against
  // TERMINAL_STATES, not just whether the key is present, or a restarted
  // backend's still-pending incident renders as if it had finished.
  const finalState = record && "finalState" in record ? (record as IncidentRecord).finalState : undefined;
  const isResolved = Boolean(finalState && TERMINAL_STATES.has(finalState));
  // The live in-progress response shape carries an explicit awaitingApproval
  // boolean; the Cloudant snapshot shape doesn't have that key at all, only
  // finalState — so a restart-recovered "AwaitingApproval" incident needs
  // to fall back to reading it off finalState instead of silently reading
  // as false (which previously made the Execution tab's approval gate show
  // "done / Auto-approved" for an incident still genuinely waiting on a
  // human decision).
  const awaitingApproval = Boolean(
    record &&
      (("awaitingApproval" in record && record.awaitingApproval) ||
        (!isResolved && finalState === "AwaitingApproval"))
  );
  const approvalSummary = record && "approvalSummary" in record ? (record.approvalSummary as string) : null;

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
      if (envelope.correlationId !== incidentId) return;
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
        connector?: string | null;
        output?: Record<string, unknown> | null;
        error?: string | null;
      };
      
      const rawAgentId = String(payload.agentId ?? payload.agent_id ?? envelope.producedBy ?? "").toLowerCase();

      if (envelope.eventType === "AgentCompleted") {
        if (rawAgentId.includes("vision")) setVisionResult(payload.result ?? null);
        else if (rawAgentId.includes("cad")) setCadResult(payload.result ?? null);
        else if (rawAgentId.includes("causal") || rawAgentId.includes("isolation")) setReasoningResult(payload.result ?? null);
        else if (rawAgentId.includes("impact") || rawAgentId.includes("simulation")) {
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
                savingsUsd: 0,
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
          connector: payload.connector,
          output: payload.output,
          error: payload.error,
        });
      }
    }

    const es = openIncidentEventStream(incidentId, handleEvent);
    api.listIncidentEvents(incidentId).then((events) => events.forEach(handleEvent)).catch(console.error);

    return () => es.close();
  }, [incidentId]);

  // Derive options from live SSE, or options query, or record alternatives fallback
  const rawOptions = liveOptions ?? optionsQuery.data?.options ?? (record && "alternatives" in record ? (record as IncidentRecord).alternatives.map((o, idx) => ({
    letter: String.fromCharCode(65 + idx),
    optionId: String(o.option_id ?? `OPT-${idx + 1}`),
    name: String(o.name ?? "Option"),
    estimatedCostUsd: Number(o.estimated_cost_usd ?? 0),
    downtimeMinutes: Number(o.downtime_minutes ?? 0),
    qualityRiskScore: Number(o.quality_risk_score ?? 0),
    overallScore: Number(o.overall_score ?? 0),
    recommendation: (o.recommendation as IncidentOption["recommendation"]) ?? "FEASIBLE",
    savingsUsd: 0,
    starRating: Math.max(1, Math.min(5, Math.round(Number(o.overall_score ?? 0) * 5))),
    isRecommended: o.recommendation === "TOP_PICK",
  })) : null);

  const optionsWithSavings = rawOptions
    ? (() => {
        const maxCost = Math.max(...rawOptions.map((o) => o.estimatedCostUsd));
        return rawOptions.map((o) => ({ ...o, savingsUsd: Math.max(0, maxCost - o.estimatedCostUsd) }));
      })()
    : null;

  async function approve(optionId?: string) {
    setApproving(true);
    try {
      await api.approveIncident(incidentId, optionId);
      queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
    } catch (e) {
      window.alert(`Approval failed: ${(e as Error).message}`);
    } finally {
      setApproving(false);
    }
  }

  const statusLabel = isResolved ? finalState : awaitingApproval ? "Awaiting Operator Approval" : "In Progress (Autonomous Reasoning)";
  const statusClass = finalState === "Resolved" ? "text-emerald" : finalState === "Failed" ? "text-status-red" : awaitingApproval ? "text-amber font-bold animate-pulse" : "text-amber";

  const activeVision = visionResult ?? (record && "visionResult" in record ? (record.visionResult as Record<string, unknown>) : null);
  const activeCad = cadResult ?? (record && "cadResult" in record ? (record.cadResult as Record<string, unknown>) : null);
  const activeReasoning = reasoningResult ?? (record && "reasoningResult" in record ? (record.reasoningResult as unknown as Record<string, unknown>) : null);

  if (incidentQuery.isError || (!incidentQuery.isLoading && !record && auditLog.length === 0)) {
    return (
      <div className="flex flex-col gap-6 p-6 rounded-xl bg-card/60 backdrop-blur-md border border-amber/40 shadow-lg">
        <div className="flex items-center gap-3">
          <span className="text-3xl">⚠️</span>
          <div>
            <h1 className="text-xl font-bold text-text-primary">Incident Session Expired or Not Found</h1>
            <p className="text-xs text-text-secondary mt-0.5">
              Incident ID <code className="text-amber font-mono">{incidentId}</code> is not in active backend memory (the backend process may have restarted).
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 pt-2 border-t border-border-subtle">
          <button
            onClick={() => router.push("/incidents")}
            className="px-4 py-2 rounded-lg text-xs font-mono font-semibold bg-cobalt text-white hover:bg-cobalt/90 transition-all"
          >
            ← View Incidents Hub
          </button>
          <button
            onClick={async () => {
              const scenario = QUALITY_ALERT_SCENARIOS.find((s) => s.lineId === "Line 2") ?? QUALITY_ALERT_SCENARIOS[0];
              const res = await api.startIncident(scenario.request);
              router.push(`/incidents/${res.incident_id}`);
            }}
            className="px-4 py-2 rounded-lg text-xs font-mono font-semibold bg-emerald text-white hover:bg-emerald/90 transition-all"
          >
            ⚡ Start Live Quality Incident Run
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <button type="button" onClick={() => router.push("/incidents")} className="w-fit text-sm text-text-secondary hover:text-cobalt">
        ← Incidents Hub
      </button>

      {isResolved && finalState === "Resolved" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald bg-emerald/10 px-5 py-3">
          <span className="font-bold text-emerald">✓ Production Resumed &amp; Incident Resolved</span>
          <div className="flex gap-4 text-sm">
            <span>
              <strong>{(record as IncidentRecord).actualDowntimeMin ?? "—"} min</strong> downtime
            </span>
            <span>
              <strong>{Math.round(((record as IncidentRecord).confidence ?? 0) * 100)}%</strong> confidence
            </span>
          </div>
        </div>
      )}

      <IncidentBriefingPlayer incidentId={incidentId} enabled={Boolean(isResolved)} />

      {awaitingApproval && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 rounded-xl border border-amber/50 bg-amber/10 p-5 shadow-lg">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-amber font-bold text-base">
              <span>⚠️ OPERATOR APPROVAL REQUIRED</span>
              <span className="px-2 py-0.5 rounded text-xs font-mono bg-amber/20 border border-amber/40">Tier 1 Governance</span>
            </div>
            <p className="text-xs text-text-primary">
              {approvalSummary || "Agentic AI pipeline completed evaluation. Human operator confirmation required before ERP / MES execution."}
            </p>
          </div>

          <button
            onClick={() => approve()}
            disabled={approving}
            className="px-5 py-2.5 rounded-lg text-sm font-semibold bg-emerald hover:bg-emerald/90 text-white shadow-md transition-all disabled:opacity-50 font-mono"
          >
            {approving ? "Executing Dispatch…" : "✓ Approve Recommendation & Resume"}
          </button>
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
              activeTab === tab ? "border-b-2 border-cobalt text-text-primary font-semibold" : "text-text-secondary hover:text-text-primary"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-border-subtle bg-card p-5">
        {activeTab === "overview" && (
          <div className="space-y-2 text-sm">
            <Row k="Incident Identifier" v={incidentId} />
            <Row k="Status" v={statusLabel ?? "—"} />
            {isResolved && <Row k="Confidence" v={`${Math.round(((record as IncidentRecord).confidence ?? 0) * 100)}%`} />}
            {isResolved && (record as IncidentRecord).approvedBy && <Row k="Approved by" v={(record as IncidentRecord).approvedBy!} />}
            {awaitingApproval && (
              <div className="pt-3">
                <button
                  onClick={() => approve()}
                  disabled={approving}
                  className="w-full py-2.5 rounded-lg text-sm font-semibold bg-emerald text-white hover:bg-emerald/90 transition-all font-mono"
                >
                  {approving ? "Approving…" : "✓ Approve Recommendation"}
                </button>
              </div>
            )}
          </div>
        )}

        {activeTab === "evidence" && (
          <div className="space-y-2 text-sm">
            {!activeVision && !activeCad && <Empty text="Waiting for Vision & CAD analysis…" />}
            {activeVision && (
              <>
                <Row k="Defect Detected" v={activeVision.defect_detected ? "Yes" : "No"} />
                <Row k="Measured Bore Diameter" v={`${activeVision.measured_value} mm`} />
                <Row k="Deviation" v={`${activeVision.deviation_mm} mm`} />
              </>
            )}
            {activeCad && (
              <>
                <Row k="Spec Violation" v={activeCad.is_violation ? `Yes (${activeCad.violation_direction})` : "No"} />
                <Row
                  k="Allowed Range"
                  v={`${(activeCad.tolerance_range as number[])?.[0] ?? "—"} – ${(activeCad.tolerance_range as number[])?.[1] ?? "—"} mm`}
                />
              </>
            )}
          </div>
        )}

        {activeTab === "reasoning" && (
          <div className="space-y-3 text-sm">
            {Boolean(activeReasoning?.llm_explanation) && (() => {
              const isLive = activeReasoning?.llm_status === "live_llm_generated";
              return (
                <div
                  className={`p-3.5 rounded-lg border space-y-1.5 font-mono text-xs ${
                    isLive ? "bg-cobalt/10 border-cobalt/30" : "bg-glass border-border-subtle"
                  }`}
                >
                  <div className={`flex items-center justify-between font-bold ${isLive ? "text-cobalt" : "text-text-secondary"}`}>
                    <span>🤖 {String(activeReasoning?.model_used ?? "Reasoning Engine")}</span>
                    {isLive ? (
                      <span className="px-2 py-0.5 rounded bg-emerald/20 text-emerald border border-emerald/30 text-[10px]">LIVE LLM</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded bg-amber/20 text-amber border border-amber/30 text-[10px]">TEMPLATE</span>
                    )}
                  </div>
                  <p className="text-text-primary leading-relaxed text-[11px] font-sans">
                    {String(activeReasoning?.llm_explanation)}
                  </p>
                </div>
              );
            })()}
            {activeReasoning?.nlu_status === "live" && <NluInsights reasoning={activeReasoning} />}
            {!activeReasoning && record && "causalChain" in record && (record as IncidentRecord).causalChain.length > 0 ? (
              <>
                <Row k="Primary Root Cause" v={(record as IncidentRecord).causalChain[0].description} />
                {(record as IncidentRecord).causalChain.map((c) => (
                  <Row key={c.conditionId} k={c.description} v={`weight ${c.weight}`} />
                ))}
              </>
            ) : !activeReasoning ? (
              <Empty text="Waiting for root-cause analysis…" />
            ) : (
              <>
                <Row k="Primary Root Cause" v={String(activeReasoning.primary_root_cause ?? "—")} />
                {(activeReasoning.ranked_causes as Array<{ name: string; weight: number }> | undefined)?.map((c) => (
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
                    <OptionCard
                      key={o.optionId}
                      option={o}
                      onApprove={awaitingApproval ? () => approve(o.optionId) : undefined}
                      approving={approving}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {activeTab === "execution" && (
          <div className="space-y-1">
            {stageRows.map((row) => (
              <StageTimelineRow key={row.agentId} row={row} />
            ))}

            {/* Governance gate - not an agent, so it's spliced into the
                timeline from awaitingApproval/record state rather than an
                AgentCompleted event. */}
            <TimelineRow
              icon="⚖️"
              label="Operator Approval Gate"
              status={awaitingApproval ? "running" : isResolved || checklist ? "done" : "pending"}
              detail={
                awaitingApproval
                  ? approvalSummary ?? "Awaiting human governance decision"
                  : isResolved && (record as IncidentRecord)?.approvedBy
                    ? `Approved by ${(record as IncidentRecord).approvedBy}`
                    : isResolved || checklist
                      ? "Auto-approved — Tier 0 autonomous"
                      : undefined
              }
            />

            {/* Capability dispatch - the real ERP/ITSM/watsonx write, from
                CapabilityInvocationStarted/Completed. */}
            <TimelineRow
              icon="🎫"
              label={checklist?.capability ?? "Capability Dispatch"}
              status={!checklist ? "pending" : checklist.phase === "started" ? "running" : "done"}
              detail={
                !checklist
                  ? undefined
                  : checklist.phase === "started"
                    ? `Dispatching ${checklist.steps.length} step(s)…`
                    : checklist.succeeded
                      ? `Fulfilled by ${checklist.connector ?? "connector"}`
                      : (checklist.error ?? "Failed")
              }
            >
              {checklist && (
                <div className="mt-1.5 space-y-1 pl-6">
                  {checklist.steps.map((step) => (
                    <div key={step} className="flex items-center gap-2 py-0.5 text-xs text-text-secondary">
                      <span className={checklist.phase === "started" ? "text-amber" : checklist.succeeded ? "text-emerald" : "text-status-red"}>
                        {checklist.phase === "started" ? "●" : checklist.succeeded ? "✓" : "✗"}
                      </span>
                      <span>{step}</span>
                    </div>
                  ))}
                  {checklist.phase === "completed" && checklist.connector && (
                    <div className="mt-2 pt-2 border-t border-border-subtle text-xs font-mono space-y-1">
                      {checklist.output &&
                        Object.entries(checklist.output).map(([key, value]) => (
                          <Row key={key} k={key} v={String(value)} />
                        ))}
                    </div>
                  )}
                </div>
              )}
            </TimelineRow>

            <StageTimelineRow row={learningRow} />
          </div>
        )}

        {activeTab === "audit" && (
          <div className="space-y-2">
            {auditLog.length === 0 && <Empty text="No events recorded yet." />}
            {auditLog.map((e) => {
              const agentId = eventAgentId(e);
              const meta = agentId ? resolveAgentMeta(agentId) : null;
              const desc = describeEvent(e);
              return (
                <details key={e.eventId} className="rounded-md border border-border-subtle bg-glass px-3 py-2 text-xs font-mono open:bg-card/60">
                  <summary className="flex cursor-pointer items-center justify-between gap-3 [&::-webkit-details-marker]:hidden">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span>{desc.icon ?? meta?.icon ?? "•"}</span>
                      <span className="font-semibold text-text-primary">{desc.title}</span>
                    </span>
                    <span className="shrink-0 text-text-secondary">{new Date(e.occurredAt).toLocaleTimeString()}</span>
                  </summary>
                  {desc.detail && <p className="mt-1.5 pl-5 text-text-secondary font-sans">{desc.detail}</p>}
                  <p className="mt-1.5 pl-5 text-[10px] text-text-secondary/70">
                    {e.eventType} · {e.producedBy}
                  </p>
                </details>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// Watson NLU pass over the watsonx reasoning text (agents/causal_isolation_agent.py).
// Only rendered when nlu_status === "live" - "not_configured"/"error" stay
// silent rather than showing empty/fabricated sentiment or keywords.
function NluInsights({ reasoning }: { reasoning: Record<string, unknown> }) {
  const sentiment = reasoning.nlu_sentiment as { score: number; label: string } | null | undefined;
  const keywords = (reasoning.nlu_keywords as string[] | undefined) ?? [];
  const categories = (reasoning.nlu_categories as string[] | undefined) ?? [];
  const sentimentClass =
    sentiment?.label === "negative" ? "text-status-red" : sentiment?.label === "positive" ? "text-emerald" : "text-text-secondary";

  return (
    <div className="p-3.5 rounded-lg bg-purple/10 border border-purple/30 space-y-2 text-xs">
      <div className="flex items-center justify-between text-purple font-bold">
        <span>🧠 IBM Watson NLU — Text Analysis</span>
        <span className="px-2 py-0.5 rounded bg-emerald/20 text-emerald border border-emerald/30 text-[10px]">LIVE</span>
      </div>
      {sentiment && (
        <div className="flex items-center justify-between">
          <span className="text-text-secondary">Sentiment</span>
          <span className={`font-mono font-semibold ${sentimentClass}`}>
            {sentiment.label} ({sentiment.score.toFixed(2)})
          </span>
        </div>
      )}
      {keywords.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {keywords.map((kw) => (
            <span key={kw} className="px-2 py-0.5 rounded-full bg-glass border border-border-subtle text-text-secondary font-mono text-[10px]">
              {kw}
            </span>
          ))}
        </div>
      )}
      {categories.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {categories.map((cat) => (
            <span key={cat} className="px-2 py-0.5 rounded-full bg-purple/10 border border-purple/20 text-purple font-mono text-[10px]">
              {cat}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// Spoken incident briefing (orchestrate/orchestrator.py's _finalize +
// GET /incidents/{id}/briefing-audio). Silently renders nothing on 404 -
// TTS_INCIDENT_BRIEFING_ENABLED is opt-in (.env.example), so "no briefing"
// is an expected state, not an error to surface.
function IncidentBriefingPlayer({ incidentId, enabled }: { incidentId: string; enabled: boolean }) {
  const audioQuery = useQuery({
    queryKey: ["incident-briefing-audio", incidentId],
    queryFn: () => api.getIncidentBriefingAudio(incidentId),
    enabled,
    retry: false,
  });

  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  useEffect(() => {
    // URL.createObjectURL allocates a real browser resource that must be
    // paired with revokeObjectURL on cleanup - it can't be computed during
    // render, so this can't be replaced with derived state despite what
    // react-hooks/set-state-in-effect's heuristic assumes.
    const url = audioQuery.data ? URL.createObjectURL(audioQuery.data) : null;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAudioUrl(url);
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [audioQuery.data]);

  if (!audioUrl) return null;

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-purple/30 bg-purple/10 px-5 py-3">
      <span className="font-bold text-purple text-sm">🔊 Spoken Briefing</span>
      { }
      <audio controls src={audioUrl} className="h-8 flex-1 min-w-[220px]" />
      <span className="text-[10px] font-mono text-text-secondary">IBM Watson Text to Speech</span>
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

function TimelineRow({
  icon,
  label,
  status,
  detail,
  children,
}: {
  icon: string;
  label: string;
  status: StageStatus;
  detail?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-border-subtle bg-glass px-3 py-2">
      <div className="flex items-center gap-2 text-sm">
        <span className={STAGE_COLOR[status]}>{STAGE_DOT[status]}</span>
        <span>{icon}</span>
        <span className={status === "pending" ? "text-text-secondary" : "font-semibold"}>{label}</span>
        <span className={`ml-auto text-[10px] font-mono uppercase ${STAGE_COLOR[status]}`}>{STAGE_LABELS[status]}</span>
      </div>
      {detail && <p className="mt-1 pl-6 text-xs text-text-secondary">{detail}</p>}
      {children}
    </div>
  );
}

function StageTimelineRow({ row }: { row: StageRow }) {
  const meta = resolveAgentMeta(row.agentId);
  const detail = describeStageResult(row.agentId, row.result);
  // Explicitly surface what generated the root-cause explanation - a live
  // local LLM call vs. the honest rule-based fallback (agents/causal_isolation_agent.py) -
  // since "what's actually doing the reasoning right now" is exactly what
  // this tab exists to answer.
  const llmNote =
    row.agentId === "causal-isolation-agent" && row.result
      ? row.result.llm_status === "live_llm_generated"
        ? `🤖 Local LLM (${row.result.model_used ?? "configured model"}) generated this explanation live`
        : `🤖 ${row.result.model_used ?? "Rule-based synthesis"} — no live LLM configured`
      : null;

  return (
    <TimelineRow icon={meta.icon} label={meta.label} status={row.status} detail={detail ?? undefined}>
      {llmNote && <p className="mt-1 pl-6 text-[11px] text-cobalt">{llmNote}</p>}
      {row.status === "done" && row.executionTimeMs !== undefined && (
        <p className="mt-0.5 pl-6 text-[10px] text-text-secondary/70">
          {row.executionTimeMs}ms · confidence {Math.round((row.confidence ?? 0) * 100)}%
        </p>
      )}
    </TimelineRow>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm italic text-text-secondary">{text}</p>;
}
