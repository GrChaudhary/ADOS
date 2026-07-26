// ADOS API client. Types are declared LITERALLY as they appear on the wire
// per endpoint, not normalized to one casing convention - the real backend
// is genuinely inconsistent field-by-field (some pydantic models declare
// camelCase aliases, some fields on those same models have no alias and
// stay snake_case, and a few raw hand-built dict endpoints are snake_case
// throughout). A normalization layer would have to special-case exactly
// the same fields this file documents anyway, for no real gain across only
// ~17 endpoints - see docs/PHASE5B_ANTIGRAVITY_HANDOFF.md for the full
// per-endpoint casing table this was verified against.

const TOKEN_KEY = "ados_service_token"; // same localStorage key as frontend/app.js and frontend/demo.js
const TOKEN_CHANGED_EVENT = "ados-token-changed";
const PROXY_BASE = "/api/backend"; // next.config.ts rewrites this to the real backend's /api/v1
const BACKEND_ORIGIN = process.env.NEXT_PUBLIC_ADOS_BACKEND_ORIGIN ?? "http://localhost:8000";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(value: string): void {
  window.localStorage.setItem(TOKEN_KEY, value);
  // Same-tab localStorage writes don't fire the native `storage` event (only
  // other tabs get that) - dispatch our own so components like useHasToken()
  // can react to a token entered in this same tab/session.
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

export function subscribeToTokenChanges(callback: () => void): () => void {
  window.addEventListener(TOKEN_CHANGED_EVENT, callback);
  return () => window.removeEventListener(TOKEN_CHANGED_EVENT, callback);
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${PROXY_BASE}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${getToken()}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${path}: ${text}`);
  }
  if (res.status === 204) return null as T;
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------
// Types - wire-literal casing per endpoint (see module docstring above)
// ---------------------------------------------------------------------

export interface MachineParameter {
  name: string;
  currentValue: number;
  targetNominal: number;
  minLimit: number;
  maxLimit: number;
  unit: string;
  lastAdjustedAt: string | null;
}

export interface DigitalTwinLine {
  lineId: string;
  plantName: string;
  status: "OPERATIONAL" | "DEGRADED" | "STOPPED";
  activeProductSku: string;
  currentSpeedUnitsPerHr: number;
  parameters: Record<string, MachineParameter>;
  telemetry: Record<string, unknown>; // untyped passthrough, snake_case keys inside
  softReservations: Record<string, unknown>[]; // untyped passthrough, snake_case keys inside
}

export interface KpiSummary {
  totalIncidents: number;
  resolvedIncidents: number;
  failedIncidents: number;
  mttrAvgMinutes: number;
  mttrMedianMinutes: number;
  revenueProtectedUsd: number;
  totalActualCostUsd: number;
  autonomyIndex: number;
  recommendationAcceptanceRate: number;
  tierDistribution: Record<string, number>;
  supplierResilience: Record<string, Record<string, unknown>>;
}

export interface IncidentOption {
  letter: string;
  optionId: string;
  name: string;
  estimatedCostUsd: number;
  downtimeMinutes: number;
  qualityRiskScore: number;
  overallScore: number;
  recommendation: "TOP_PICK" | "FEASIBLE" | "REJECTED";
  savingsUsd: number;
  starRating: number;
  isRecommended: boolean;
}

export interface IncidentComparison {
  incidentId: string;
  options: IncidentOption[];
}

export interface CausalChainEntry {
  conditionId: string;
  description: string;
  weight: number;
  evidencePath: string[];
}

export interface IncidentRecord {
  incidentId: string;
  plantId: string;
  lineId: string;
  detectedAt: string;
  resolvedAt: string | null;
  finalState: string; // "Resolved" | "Failed"
  causalChain: CausalChainEntry[];
  confidence: number;
  alternatives: Record<string, unknown>[];
  policyTier: 0 | 1 | 2;
  approvedBy: string | null;
  recommendationAccepted: boolean | null;
  capabilityInvoked: string | null;
  capabilityStatus: string | null;
  supplierId: string | null;
  estimatedCostUsd: number | null;
  actualCostUsd: number | null;
  estimatedDowntimeMin: number | null;
  actualDowntimeMin: number | null;
  createdAt: string;
}

export interface IncidentInProgress {
  incidentId: string;
  status: "in_progress";
  awaitingApproval: boolean;
  approvalSummary: unknown | null;
}

// StartIncidentRequest/Response are the one clear outlier: no aliases
// declared on these two backend models at all, so both stay snake_case.
export interface StartIncidentRequest {
  plant_id: string;
  line_id: string;
  part_number: string;
  vision_data: Record<string, unknown>;
  priority: {
    safety_impact: number;
    customer_impact: number;
    line_down_cost_per_hour_usd: number;
    production_priority: number;
    is_systemic: boolean;
  };
}

export interface StartIncidentResponse {
  incident_id: string;
  status: string;
}

export interface EventEnvelope<TPayload = Record<string, unknown>> {
  eventId: string;
  eventType: string;
  incidentId: string;
  occurredAt: string;
  producedBy: string;
  schemaVersion: string;
  payload: TPayload;
}

// ---------------------------------------------------------------------
// Endpoint functions - the extension point for Phase 5B's 5 screens: add
// functions here, don't create a second client.
// ---------------------------------------------------------------------

export const api = {
  getDigitalTwinLines: () => apiFetch<DigitalTwinLine[]>("/digital-twin/lines"),
  getKpis: () => apiFetch<KpiSummary>("/executive/kpis"),
  startIncident: (body: StartIncidentRequest) =>
    apiFetch<StartIncidentResponse>("/incidents", { method: "POST", body: JSON.stringify(body) }),
  getIncident: (id: string) => apiFetch<IncidentRecord | IncidentInProgress>(`/incidents/${id}`),
  listIncidentEvents: (incidentId: string) => apiFetch<EventEnvelope[]>(`/events?incident_id=${incidentId}`),
  approveIncident: (id: string, approvedBy: string) =>
    apiFetch<{ incidentId: string; decision: string }>(`/incidents/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: approvedBy }),
    }),
  getIncidentOptions: (id: string) => apiFetch<IncidentComparison>(`/executive/incidents/${id}/options`),
};

/**
 * Opens a live SSE connection for one incident's events, filtered
 * server-side. Connects directly to the backend origin (not the Next.js
 * rewrite proxy - see next.config.ts) since EventSource can't reliably
 * traverse a rewrite for a long-lived stream, and can't set an
 * Authorization header, hence the ?token= query param.
 */
export function openIncidentEventStream(
  incidentId: string,
  onEvent: (envelope: EventEnvelope) => void
): EventSource {
  const url = `${BACKEND_ORIGIN}/events/stream?token=${encodeURIComponent(getToken())}&incident_id=${encodeURIComponent(incidentId)}`;
  const es = new EventSource(url);
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data));
    } catch (err) {
      console.error("Failed to parse SSE event", err);
    }
  };
  return es;
}
