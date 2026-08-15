"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, CapabilityRequestView } from "@/lib/api";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { useHasToken } from "@/lib/useHasToken";

// backend/app/routers/runtime_approvals.py's full status lifecycle
// (orchestrate/runtime/capability_execution.py). "pending_approval" is the
// only one a human can act on; the rest are read-only history/state.
const STATUS_FILTERS = [
  "pending_approval",
  "executing",
  "executed",
  "failed",
  "outcome_unknown",
  "denied",
] as const;

function statusBadgeClass(status: string): string {
  switch (status) {
    case "pending_approval":
      return "bg-amber/20 text-amber border-amber/40";
    case "executed":
      return "bg-emerald/20 text-emerald border-emerald/40";
    case "executing":
      return "bg-cobalt/20 text-cobalt border-cobalt/40";
    case "outcome_unknown":
      return "bg-status-red/20 text-status-red border-status-red/40 animate-pulse";
    case "failed":
    case "denied":
      return "bg-status-red/20 text-status-red border-status-red/40";
    default:
      return "bg-glass text-text-secondary border-border-subtle";
  }
}

/** Parses apiFetch's `"${status} ${path}: ${body}"` Error.message so a 409
 * (already decided / session not live / no token expiry — all real,
 * meaningful conflicts, not failures) can be shown distinctly from a
 * generic error, per the requirement that the UI must not conflate the two. */
function parseApiError(err: unknown): { code: number | null; message: string } {
  const message = err instanceof Error ? err.message : String(err);
  const match = message.match(/^(\d{3}) /);
  return { code: match ? Number(match[1]) : null, message };
}

function RequestCard({ request }: { request: CapabilityRequestView }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["capability-requests"] });

  const approveMutation = useMutation({
    mutationFn: () => api.approveCapabilityRequest(request.requestId),
    onSuccess: invalidate,
  });
  const rejectMutation = useMutation({
    mutationFn: () => api.rejectCapabilityRequest(request.requestId, reason || undefined),
    onSuccess: () => {
      invalidate();
      setShowRejectForm(false);
      setReason("");
    },
  });

  const isPending = request.status === "pending_approval";
  const activeError = approveMutation.error ?? rejectMutation.error;
  const parsedError = activeError ? parseApiError(activeError) : null;

  return (
    <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-3 font-mono text-xs">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-text-primary text-sm">{request.capability}</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${statusBadgeClass(request.status)}`}>
              {request.status}
            </span>
          </div>
          <div className="text-text-secondary text-[11px] mt-1">
            request {request.requestId.slice(0, 8)}… · mission {request.missionId.slice(0, 8)}… · session{" "}
            {request.sessionId.slice(0, 8)}…
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-emerald">${request.estimatedCostUsd.toLocaleString("en-US")}</div>
          {request.policyTier !== null && <div className="text-text-secondary text-[10px]">tier {request.policyTier}</div>}
        </div>
      </div>

      {request.status === "outcome_unknown" && (
        <div className="p-2 rounded-lg bg-status-red/10 border border-status-red/30 text-status-red text-[11px]">
          Outcome unknown — the approved call&apos;s real-world result could not be confirmed. Requires a human to
          check the external system directly; this is neither a success nor a failure.
        </div>
      )}

      {request.riskClass && (
        <div className="text-text-secondary">
          risk: <span className="text-text-primary">{request.riskClass}</span>
        </div>
      )}

      {Object.keys(request.arguments ?? {}).length > 0 && (
        <details className="text-text-secondary">
          <summary className="cursor-pointer hover:text-text-primary">arguments</summary>
          <pre className="mt-1 p-2 rounded-lg bg-card/60 overflow-x-auto text-[10px]">
            {JSON.stringify(request.arguments, null, 2)}
          </pre>
        </details>
      )}

      {(request.decidedBy || request.reason) && (
        <div className="text-text-secondary text-[11px]">
          {request.decidedBy && <div>decided by: {request.decidedBy}</div>}
          {request.reason && <div>reason: {request.reason}</div>}
        </div>
      )}

      {isPending && (
        <div className="space-y-2 pt-1">
          <div className="flex gap-2">
            <button
              type="button"
              disabled={approveMutation.isPending || rejectMutation.isPending}
              onClick={() => approveMutation.mutate()}
              className="px-3 py-1.5 rounded-lg bg-emerald text-white font-semibold hover:bg-emerald/80 transition-all disabled:opacity-50"
            >
              {approveMutation.isPending ? "Approving…" : "Approve"}
            </button>
            <button
              type="button"
              disabled={approveMutation.isPending || rejectMutation.isPending}
              onClick={() => setShowRejectForm((v) => !v)}
              className="px-3 py-1.5 rounded-lg bg-status-red/20 text-status-red border border-status-red/40 font-semibold hover:bg-status-red/30 transition-all disabled:opacity-50"
            >
              Reject
            </button>
          </div>
          {showRejectForm && (
            <div className="flex gap-2">
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="reason (optional)"
                className="flex-1 px-2 py-1.5 rounded-lg bg-card/60 border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
              />
              <button
                type="button"
                disabled={rejectMutation.isPending}
                onClick={() => rejectMutation.mutate()}
                className="px-3 py-1.5 rounded-lg bg-status-red text-white font-semibold hover:bg-status-red/80 transition-all disabled:opacity-50"
              >
                Confirm reject
              </button>
            </div>
          )}
        </div>
      )}

      {parsedError && (
        <div className="p-2 rounded-lg bg-status-red/10 border border-status-red/40 text-status-red text-[11px]">
          {parsedError.code === 409 ? (
            <>Conflict — this request was likely already decided, or its session is no longer live. {parsedError.message}</>
          ) : parsedError.code === 403 ? (
            <>Not authorized to decide this request (role or approval-limit restriction). {parsedError.message}</>
          ) : (
            parsedError.message
          )}
        </div>
      )}
    </div>
  );
}

export default function RuntimeApprovalsPage() {
  const currentUser = useCurrentUser();
  const hasToken = useHasToken();
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("pending_approval");

  const requestsQuery = useQuery({
    queryKey: ["capability-requests", statusFilter],
    queryFn: () => api.listCapabilityRequests(statusFilter),
    enabled: hasToken,
    refetchInterval: 10000,
  });

  if (!currentUser) {
    return <p className="text-sm text-text-secondary">Log in to view this page.</p>;
  }

  const requests = requestsQuery.data?.requests ?? [];

  return (
    <div className="space-y-6 pb-8">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Runtime Capability Approvals</h1>
          <p className="text-sm text-text-secondary mt-1">
            The human half of the Prime Agent&apos;s Tier 1/2 approval loop —{" "}
            <code className="text-emerald">backend/app/routers/runtime_approvals.py</code>. Every approve/reject
            here is enforced server-side (role, approval limit, tenant, session liveness) — this page only
            reflects those decisions, it never makes them.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold border transition-all ${
              statusFilter === s
                ? "bg-cobalt/20 text-cobalt border-cobalt/40"
                : "bg-glass text-text-secondary border-border-subtle hover:text-text-primary"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-3 shadow-lg">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text-primary">Queue</h2>
          <span className="text-xs font-mono text-text-secondary">{requestsQuery.data?.count ?? 0} requests</span>
        </div>

        {requestsQuery.isLoading && <p className="text-xs text-text-secondary">Loading capability requests…</p>}
        {requestsQuery.isError && (
          <p className="text-xs text-status-red">
            Could not load capability requests. {(requestsQuery.error as Error).message}
          </p>
        )}
        {!requestsQuery.isLoading && !requestsQuery.isError && requests.length === 0 && (
          <p className="text-xs text-text-secondary py-6 text-center">
            No requests with status &quot;{statusFilter}&quot;.
          </p>
        )}

        <div className="space-y-3">
          {requests.map((request) => (
            <RequestCard key={request.requestId} request={request} />
          ))}
        </div>
      </div>
    </div>
  );
}
