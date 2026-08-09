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
const USER_KEY = "ados_current_user"; // RBAC (backend/app/rbac.py) - the User returned by /auth/login|me
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

// useSyncExternalStore (useCurrentUser.ts) requires getSnapshot to return
// a stable (===) reference when nothing changed - JSON.parse-ing
// localStorage fresh on every call returns a new object every time even
// when the raw string is identical, which reads as "the store changed"
// on every render and causes an infinite update loop. Cache the parsed
// result and only re-parse when the raw string actually changes.
let _cachedUserRaw: string | null = null;
let _cachedUser: AuthUser | null = null;

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (raw === _cachedUserRaw) return _cachedUser;
  _cachedUserRaw = raw;
  if (!raw) {
    _cachedUser = null;
    return null;
  }
  try {
    _cachedUser = JSON.parse(raw) as AuthUser;
  } catch {
    _cachedUser = null;
  }
  return _cachedUser;
}

function setStoredUser(user: AuthUser): void {
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

/** Logs the current session out client-side: clears the stored JWT + user.
 * Called both by an explicit "Log out" click and automatically by
 * apiFetch() on a 401 (expired/invalid session). */
export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
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
  if (res.status === 401) {
    // Session expired/invalid (backend/app/rbac.py) - clear it and send the
    // user back to log in rather than surfacing a raw fetch error on every
    // query on the page.
    clearSession();
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${path}: ${text}`);
  }
  if (res.status === 204) return null as T;
  return res.json() as Promise<T>;
}

// Binary responses (audio) can't go through apiFetch's res.json() - and
// unlike EventSource, a plain fetch() can set the Authorization header, so
// (unlike openIncidentEventStream below) this doesn't need a ?token= param.
async function apiFetchBlob(path: string): Promise<Blob> {
  const res = await fetch(`${PROXY_BASE}${path}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${path}`);
  }
  return res.blob();
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

export interface ReasoningResult {
  defect_type: string;
  primary_root_cause: string;
  primary_condition_id: string | null;
  root_cause_confidence: number;
  llm_status: string;
  llm_explanation: string | null;
  model_used: string | null;
  nlu_status: string;
  nlu_sentiment: string | null;
  nlu_keywords: string[];
  nlu_categories: string[];
  ranked_causes: Array<{
    rank: number;
    condition_id: string;
    name: string;
    weight: number;
    evidence_path: string[];
  }>;
  affected_products: string[];
  governing_spec: string | null;
}

export interface IncidentInProgress {
  incidentId: string;
  status: "in_progress";
  awaitingApproval: boolean;
  approvalSummary: unknown | null;
  causalChain: CausalChainEntry[];
  alternatives: Record<string, unknown>[];
  confidence: number;
  policyTier: 0 | 1 | 2;
  reasoningResult: ReasoningResult | null;
  visionResult: Record<string, unknown> | null;
  cadResult: Record<string, unknown> | null;
}

export interface CausalSynthesisResult {
  status: string;
  model_used: string | null;
  explanation: string | null;
  error?: string;
  causalChain: CausalChainEntry[];
}

// Snake_case throughout - hand-built dict response from
// knowledge/policy_docs_qa.py:answer_question, no pydantic aliasing.
export interface CopilotSource {
  doc: string;
  heading: string;
}

export interface CopilotAskResult {
  status: string;
  model_used: string | null;
  answer: string | null;
  sources: CopilotSource[];
  error?: string;
  llm_error?: string;
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
  correlationId: string;
  occurredAt: string;
  producedBy: string;
  schemaVersion: string;
  traceId?: string | null;
  idempotencyKey?: string | null;
  payload: TPayload;
}

export interface EnterpriseIntelligenceSummary {
  revenueProtectedUsd: number;
  totalActualCostUsd: number;
  mttrAvgMinutes: number;
  autonomyIndex: number;
  recommendationAcceptanceRate: number;
  supplierRiskResilience: Record<string, Record<string, unknown>>;
  strategicRecommendationsCount: number;
  topPlantRiskDriver: string;
}

export interface StrategicRecommendation {
  recommendationId: string;
  category: string;
  title: string;
  summary: string;
  impact_level?: string;
  estimatedAnnualSavingsUsd: number;
  supportingEvidence: string[];
  actionItems: string[];
}

// Raw hand-built dict, snake_case throughout - no pydantic response_model
// on GET /executive/kpis/what-if, so nothing aliases it to camelCase.
export interface WhatIfSimulation {
  target_condition_id: string;
  promoted_to_tier: string;
  baseline: { mttr_avg_min: number; autonomy_index: number; revenue_protected_usd: number };
  simulated: { mttr_avg_min: number; autonomy_index: number; revenue_protected_usd: number };
  delta: { mttr_reduction_min: number; autonomy_increase_pct: number; additional_revenue_protected_usd: number };
}

export interface RiskSignal {
  signalId: string;
  plantId: string;
  lineId: string;
  risk_score: number;
  risk_level: string;
  primaryRiskDriver: string;
  causalConditionId: string;
  recommendedMitigation: string;
}

export interface DecisionMemoryQuery {
  plantId?: string;
  lineId?: string;
  defectType?: string;
  conditionId?: string;
  supplierId?: string;
  minConfidence?: number;
  limit?: number;
}

export interface DecisionMemorySearchResult {
  totalMatches: number;
  records: IncidentRecord[];
  relevanceScores: number[];
}

export interface LearningReplaySummary {
  recordsProcessed: number;
  edgesUpdated: number;
  weightAdjustments: Record<string, unknown>[];
  timestamp: string;
}

export interface PolicyPromotionCandidate {
  candidateId: string;
  conditionId: string;
  decisionClassName: string;
  currentTier: string;
  targetTier: string;
  sampleVolume: number;
  operatorAcceptanceRate: number;
  avgConfidence: number;
  isEligible: boolean;
  promotionRationale: string;
  safetyGuardrails: string[];
}

export interface GraphNode {
  id: string;
  type: "PRODUCT" | "PART" | "SUPPLIER";
  label: string;
  detail: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: "BOM" | "SUPPLIES" | "SUBSTITUTE";
  label: string | null;
}

export interface KnowledgeGraphSnapshot {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface IntegrationConnectorItem {
  id: string;
  name: string;
  status: string;
  auth: string;
  module: string;
  description: string;
  capabilities: string[];
  connected: boolean;
  latency_ms?: number;
  doc_count?: number;
  host?: string;
  database_name?: string;
}

// LLM provider settings (backend/app/routers/settings.py) — self-service
// replacement for hand-editing .env's NEMOTRON_API_KEY / OPENAI_API_KEY /
// ANTHROPIC_API_KEY. One shared key per provider for the whole deployment,
// admin-managed. api_key/model here are always write-only inputs — the
// backend never echoes a saved key back, only a maskedKey preview.
export interface LLMProviderStatus {
  provider: "nemotron" | "openai" | "anthropic";
  configured: boolean;
  model: string;
  masked_key: string | null;
  role: string;
  name: string;
  auth: string;
  description: string;
  host?: string;
  status: string;
  connected: boolean;
}

export interface LLMProvidersResponse {
  providers: LLMProviderStatus[];
  ollama: Omit<LLMProviderStatus, "provider" | "masked_key"> & { host?: string; thinkingEnabled?: boolean };
  activeProvider?: string;
  activeProviderSource?: string;
}


export interface LLMProviderTestResult {
  success: boolean;
  message: string;
  model_used?: string | null;
  latency_ms?: number | null;
}

// Manual capability invocation (backend/app/routers/capabilities.py's
// POST /capabilities/invoke) - bypasses the whole incident pipeline
// (vision/causal/governance stages); the caller supplies the governance
// decision itself. contracts/capabilities.py's Capability/PolicyTier/
// CallStatus enums, contracts/capability_call.py's CapabilityCall/
// GovernanceInfo/CapabilityResponse models.
export type Capability =
  | "CreatePurchaseOrder"
  | "CreateIncident"
  | "ReserveInventory"
  | "NotifyOperator"
  | "UpdateMES"
  | "CreateChangeRequest"
  | "ScheduleMaintenance"
  | "QueryExternalStock"
  | "CreateExternalPO"
  | "GetFreightQuote"
  | "QueryDatabase";

export type PolicyTier = 0 | 1 | 2; // AUTONOMOUS | APPROVAL_REQUIRED | EXECUTIVE_APPROVAL

export interface CapabilityCallRequest {
  capability: Capability;
  incidentId: string;
  requestedBy: string;
  input: Record<string, unknown>;
  governance: {
    policyTier: PolicyTier;
    approvedBy?: string | null;
  };
}

export interface CapabilityCallResponse {
  requestId: string;
  status: "succeeded" | "failed" | "rolled_back";
  connector: string | null;
  output: Record<string, unknown>;
  error: string | null;
  compensatingActionRan: boolean;
  occurredAt: string;
}

export type AgentTier =
  | "Tier 0 (Autonomous)"
  | "Tier 1 (Engineer Approval)"
  | "Tier 2 (Multi-Executive)";

export type AgentStage =
  | "Perception"
  | "Reasoning"
  | "CandidateGen"
  | "Evaluation"
  | "Execution"
  | "Learning";

export interface AgentRegistryEntry {
  id: string;
  label: string;
  icon: string;
  color: string;
  description: string;
  model: string;
  inputSchema: string;
  outputSchema: string;
  memoryRAG: boolean;
  targetTier: AgentTier;
  stage: AgentStage;
  isBuiltIn: boolean;
  instructions: string;
  createdAt: string;
}

// RBAC (backend/app/rbac.py) - real per-user login, replacing the shared
// service-token box that used to be the only "auth" in this app.
export type Role = "manager" | "executive" | "admin" | "auditor";

export interface AuthUser {
  userId: string;
  username: string;
  displayName: string;
  role: Role;
  approvalLimitUsd: number;
  active: boolean;
}

export interface LoginResponse {
  token: string;
  user: AuthUser;
}

export interface GovernancePolicies {
  financialExposureBands: {
    lowExposureMaxUsd: number;
    highExposureMinUsd: number;
    tier0ConfidenceThreshold: number;
    source: string;
  };
  capabilityRiskClass: Record<string, string>;
  rbacApprovalRules: string[];
  itsmLiveWriteGate: {
    connectorEligible: boolean;
    liveWritesEnabled: boolean;
    source: string;
  };
}

export interface CreateAgentRequest {
  label: string;
  icon: string;
  color: string;
  description: string;
  model: string;
  inputSchema: string;
  outputSchema: string;
  memoryRAG: boolean;
  targetTier: AgentTier;
  stage: AgentStage;
  instructions: string;
}

export const api = {
  getDigitalTwinLines: () => apiFetch<DigitalTwinLine[]>("/digital-twin/lines"),
  getKpis: () => apiFetch<KpiSummary>("/executive/kpis"),
  getEnterpriseSummary: () => apiFetch<EnterpriseIntelligenceSummary>("/executive/enterprise"),
  getWhatIf: (conditionId = "COND-TOL-DRIFT") => apiFetch<WhatIfSimulation>(`/executive/kpis/what-if?condition_id=${encodeURIComponent(conditionId)}`),
  getRiskSignals: () => apiFetch<RiskSignal[]>("/executive/risk"),
  getStrategicRecommendations: () => apiFetch<StrategicRecommendation[]>("/executive/recommendations"),
  startIncident: (body: StartIncidentRequest) =>
    apiFetch<StartIncidentResponse>("/incidents", { method: "POST", body: JSON.stringify(body) }),
  getIncident: (id: string) => apiFetch<IncidentRecord | IncidentInProgress>(`/incidents/${id}`),
  listIncidents: (limit = 100) => apiFetch<IncidentRecord[]>(`/incidents?limit=${limit}`),
  getCausalSynthesis: (id: string) => apiFetch<CausalSynthesisResult>(`/incidents/${id}/causal-synthesis`),
  listIncidentEvents: (incidentId: string) => apiFetch<EventEnvelope[]>(`/events?correlation_id=${incidentId}`),
  listAllEvents: (limit = 200) => apiFetch<EventEnvelope[]>(`/events?limit=${limit}`),
  // approved_by is no longer client-supplied - the backend derives it from
  // the caller's session (backend/app/rbac.py), so this takes no identity
  // argument anymore and the request has no body.
  approveIncident: (id: string, selectedOptionId?: string) =>
    apiFetch<{ incidentId: string; decision: string }>(`/incidents/${id}/approve`, {
      method: "POST",
      body: selectedOptionId ? JSON.stringify({ selected_option_id: selectedOptionId }) : undefined,
    }),
  getIncidentOptions: (id: string) => apiFetch<IncidentComparison>(`/executive/incidents/${id}/options`),
  searchDecisionMemory: (query: DecisionMemoryQuery) =>
    apiFetch<DecisionMemorySearchResult>("/memory/search", { method: "POST", body: JSON.stringify(query) }),
  getLearningRecalibration: (learningRate = 0.08) => apiFetch<LearningReplaySummary>(`/learning/recalibration?learning_rate=${learningRate}`),
  getPromotionCandidates: () => apiFetch<PolicyPromotionCandidate[]>("/learning/promotion-candidates"),
  getKnowledgeGraph: () => apiFetch<KnowledgeGraphSnapshot>("/knowledge/graph"),
  getIntegrationsStatus: () => apiFetch<IntegrationConnectorItem[]>("/integrations/status"),
  // LLM provider settings — Settings page
  getLLMProviders: () => apiFetch<LLMProvidersResponse>("/settings/llm-providers"),
  setActiveLLMProvider: (provider: string) =>
    apiFetch<{ activeProvider: string; activeProviderSource: string }>("/settings/active-provider", {
      method: "PUT",
      body: JSON.stringify({ provider }),
    }),
  toggleThinkingMode: (enabled: boolean) =>

    apiFetch<LLMProvidersResponse["ollama"]>("/settings/llm-providers/ollama/thinking", {
      method: "PUT",
      body: JSON.stringify({ thinkingEnabled: enabled }),
    }),
  saveLLMProviderKey: (provider: string, body: { apiKey: string; model?: string }) =>
    apiFetch<LLMProviderStatus>(`/settings/llm-providers/${provider}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteLLMProviderKey: (provider: string) =>
    apiFetch<LLMProviderStatus>(`/settings/llm-providers/${provider}`, { method: "DELETE" }),
  testLLMProvider: (provider: string) =>
    apiFetch<LLMProviderTestResult>(`/settings/llm-providers/${provider}/test`, { method: "POST" }),
  invokeCapability: (body: CapabilityCallRequest) =>
    apiFetch<CapabilityCallResponse>("/capabilities/invoke", { method: "POST", body: JSON.stringify(body) }),
  // 404 when TTS_INCIDENT_BRIEFING_ENABLED isn't set on the backend or the
  // incident hasn't reached a terminal state yet - callers should treat
  // that as "no briefing", not an error banner (see .env.example).
  getIncidentBriefingAudio: (id: string) => apiFetchBlob(`/incidents/${id}/briefing-audio`),
  // Agent Registry — dynamic, Cloudant-backed
  listAgents: () => apiFetch<AgentRegistryEntry[]>("/agents-registry"),
  getStageTemplates: () => apiFetch<Record<string, Omit<AgentRegistryEntry, "id" | "label" | "isBuiltIn" | "createdAt">>>("/agents-registry/stage-templates"),
  createAgent: (body: CreateAgentRequest) =>
    apiFetch<AgentRegistryEntry>("/agents-registry", { method: "POST", body: JSON.stringify(body) }),
  deleteAgent: (id: string) => apiFetch<null>(`/agents-registry/${id}`, { method: "DELETE" }),
  // RBAC (backend/app/routers/auth.py)
  login: async (username: string, password: string) => {
    const res = await apiFetch<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setToken(res.token);
    setStoredUser(res.user);
    return res;
  },
  getCurrentUser: () => apiFetch<AuthUser>("/auth/me"),
  listUsers: () => apiFetch<AuthUser[]>("/auth/users"),
  createUser: (body: { username: string; password: string; display_name: string; role: Role; approval_limit_usd: number }) =>
    apiFetch<AuthUser>("/auth/users", { method: "POST", body: JSON.stringify(body) }),
  getGovernancePolicies: () => apiFetch<GovernancePolicies>("/governance/policies"),
  askCopilot: (question: string) =>
    apiFetch<CopilotAskResult>("/copilot/ask", { method: "POST", body: JSON.stringify({ question }) }),
  // MOA (Main Orchestrating Agent)
  createMOATask: (body: MOATaskRequest) =>
    apiFetch<MOATaskResponse>("/moa/tasks", { method: "POST", body: JSON.stringify(body) }),
  approveMOATask: (args: { taskId: string; editedArguments?: Record<string, unknown> } | string) => {
    const taskId = typeof args === "string" ? args : args.taskId;
    const editedArguments = typeof args === "string" ? undefined : args.editedArguments;
    return apiFetch<MOATaskResponse>(`/moa/tasks/${taskId}/approve`, {
      method: "POST",
      body: JSON.stringify(editedArguments ? { edited_arguments: editedArguments } : {}),
    });
  },
  rejectMOATask: (taskId: string) =>
    apiFetch<MOATaskResponse>(`/moa/tasks/${taskId}/reject`, { method: "POST" }),
  // LangGraph Agents
  askExecutiveCopilotLangGraph: (query: string) =>
    apiFetch<ExecutiveCopilotAskResponse>("/agents/executive-copilot/ask", { method: "POST", body: JSON.stringify({ query }) }),
  askITSMAgent: (query: string) =>
    apiFetch<ITSMAskResponse>("/agents/itsm/ask", { method: "POST", body: JSON.stringify({ query }) }),
  approveITSMAgentAction: (requestId: string) =>
    apiFetch<ITSMAskResponse>(`/agents/itsm/${requestId}/approve`, { method: "POST" }),
  rejectITSMAgentAction: (requestId: string) =>
    apiFetch<ITSMAskResponse>(`/agents/itsm/${requestId}/reject`, { method: "POST" }),
  // Capability Manifest Registry & Circuit Breaker
  getCapabilityManifests: () => apiFetch<CapabilityManifest[]>("/capabilities/manifests"),
  promoteCapabilityManifest: (id: string) =>
    apiFetch<{ status: string }>(`/capabilities/manifests/${id}/promote`, { method: "POST" }),
  disableCapabilityManifest: (id: string) =>
    apiFetch<{ status: string }>(`/capabilities/manifests/${id}/disable`, { method: "POST" }),
  getCircuitBreakerStatus: () => apiFetch<CircuitBreakerStatus>("/governance/circuit-breaker"),
  clearCircuitBreaker: () => apiFetch<{ status: string }>("/governance/circuit-breaker/clear", { method: "POST" }),
  generateObsidianProjection: () =>
    apiFetch<{ status: string; target_dir: string; generated_notes_count: number }>("/governance/obsidian-projection", { method: "POST" }),
  getObsidianProjectionStatus: () => apiFetch<ObsidianProjectionStatusResponse>("/governance/obsidian-projection/status"),
  syncObsidianVault: () =>
    apiFetch<{ status: string; target_dir: string; reconciled_files_count: number; total_vault_notes: number }>("/governance/obsidian-projection/sync", { method: "POST" }),
  // Capability Onboarding (Phase 7 — BYOC Studio)
  getOnboardingSessions: () => apiFetch<OnboardingSession[]>("/capability-onboarding/sessions"),
  getOnboardingSession: (id: string) => apiFetch<OnboardingSession>(`/capability-onboarding/sessions/${id}`),
  startOnboardingSession: (body: StartOnboardingPayload) =>
    apiFetch<StartOnboardingResponse>("/capability-onboarding/sessions", { method: "POST", body: JSON.stringify(body) }),
  synthesizeOnboardingSession: (args: { id: string; payload: SynthesizeSessionPayload }) =>
    apiFetch<SynthesizeSessionResponse>(`/capability-onboarding/sessions/${args.id}/synthesize`, {
      method: "POST",
      body: JSON.stringify(args.payload),
    }),
  proposeRiskOnboardingSession: (id: string) =>
    apiFetch<RiskProposalResponse>(`/capability-onboarding/sessions/${id}/risk-proposal`, { method: "POST", body: JSON.stringify({}) }),
  sandboxTestOnboardingSession: (args: { id: string; payload: SandboxTestPayload }) =>
    apiFetch<SandboxTestResponse>(`/capability-onboarding/sessions/${args.id}/sandbox-test`, {
      method: "POST",
      body: JSON.stringify(args.payload),
    }),
  activateOnboardingSession: (id: string) =>
    apiFetch<ActivateSessionResponse>(`/capability-onboarding/sessions/${id}/activate`, { method: "POST", body: JSON.stringify({}) }),
};

// ---------------------------------------------------------------------
// MOA & LangGraph Agent Interfaces
// ---------------------------------------------------------------------

export interface MOATaskRequest {
  domain: string;
  employee_name: string;
  instruction: string;
}

export interface MOATaskResponse {
  status: "ok" | "pending_approval" | "error" | "not_configured" | string;
  taskId?: string;
  answer?: string;
  toolsCalled?: string[];
  modelUsed?: string;
  proposedAction?: {
    action_key: string;
    capability: string;
    summary: string;
    estimated_cost_usd: number;
    policy_tier: PolicyTier;
    arguments?: Record<string, unknown>;
    input_schema?: Record<string, unknown>;
  };
  approvalDecision?: string;
  trajectoryLog?: Array<{
    step: number;
    type: string;
    thought: string;
    action?: string;
    capability?: string;
    policy_tier?: number;
    status: string;
    timestamp: string;
  }>;
}

export interface ITSMAskResponse {
  status: "ok" | "pending_approval" | "not_configured" | "error" | "max_iterations_exceeded" | string;
  requestId?: string;
  answer?: string | null;
  toolsCalled?: string[];
  modelUsed?: string | null;
  proposedIncident?: { short_description: string; description: string } | null;
  approvalDecision?: string;
}

export interface ExecutiveCopilotAskResponse {
  status: string;
  answer: string;
  toolsCalled?: string[];
  modelUsed?: string;
}

// backend/app/routers/capabilities.py's GET /manifests + promote/disable —
// real endpoints as of this session, backed by
// integrations/capability_manifest.py's CapabilityManifestRegistry
// (Postgres-backed). sandbox_evidence is the registry's actual shape: a
// free-text description of what was run (e.g. "ran 12/12 checks"), NOT a
// structured {tested_at, passed_checks, total_checks} object — there is
// no such object anywhere in the backend, don't parse it as one.
export interface CapabilityManifest {
  capability_id: string;
  display_name: string;
  domain: string;
  version: string;
  source: string;
  proposed_by: string;
  status: "proposed" | "sandbox_tested" | "active" | "deprecated" | "hot_disabled";
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  requires_governance: boolean;
  sandbox_evidence: string | null;
  usage_count: number;
  registered_at: string;
}

// There is deliberately no single global circuit breaker in ADOS —
// orchestrate/moa/graph.py creates one CascadeCircuitBreaker PER MOA task
// (see that module's docstring). This endpoint reports an honest
// aggregate over the currently-live per-task breakers (only tasks
// actively paused awaiting a human have a live breaker to count):
// state/auto_approved_count/threshold describe the most-open case across
// them (OPEN if ANY task's breaker is open), active_tasks/open_task_ids
// make that per-task scoping visible instead of hiding it behind a fake
// single global number.
export interface CircuitBreakerStatus {
  state: "CLOSED" | "OPEN";
  auto_approved_count: number;
  threshold: number;
  active_tasks: number;
  open_task_ids: string[];
}


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
  const url = `${BACKEND_ORIGIN}/events/stream?token=${encodeURIComponent(getToken())}&correlation_id=${encodeURIComponent(incidentId)}`;
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

// ---------------------------------------------------------------------
// Capability Onboarding (Phase 7 — BYOC Studio) Interfaces
// ---------------------------------------------------------------------

export type OnboardingTrack = "mcp_native" | "openapi";

export type OnboardingSessionStatus =
  | "submitted"
  | "inspected"
  | "synthesized"
  | "risk_reviewed"
  | "sandbox_tested"
  | "activated"
  | "failed"
  | "aborted";

export interface DiscoveredTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  runtime: Record<string, unknown>;
}

export interface InspectionReport {
  source: string;
  track: OnboardingTrack | null;
  confidence: "high" | "inferred" | "hinted" | "none";
  local_path: string | null;
  resolved_ref: string | null;
  language: string | null;
  tools: DiscoveredTool[];
  warnings: string[];
  launch_command: string[] | null;
  openapi_spec_path: string | null;
}

export interface SynthesizedAction {
  key: string;
  description: string;
  capability_id: string;
  domain: string;
  version: string;
  estimated_cost_usd: number;
  track: OnboardingTrack;
  runtime: Record<string, unknown>;
}

export interface SandboxResult {
  passed: boolean;
  evidence_summary: string;
  raw_output: string;
  duration_ms: number;
}

export interface AuditLogEntry {
  turn: number;
  actor: string;
  at: string;
  detail: string;
}

export interface OnboardingSession {
  id: string;
  track: OnboardingTrack | null;
  status: OnboardingSessionStatus;
  source_url: string;
  domain: string | null;
  capability_id: string | null;
  selected_tool_name: string | null;
  inspection_report: InspectionReport | null;
  synthesized_manifest: SynthesizedAction | null;
  sandbox_result: SandboxResult | null;
  audit_log: AuditLogEntry[];
  created_by: string;
  created_at: string;
  updated_at: string;
  failure_reason: string | null;
}

export interface StartOnboardingPayload {
  source_url: string;
  track_hint?: OnboardingTrack;
}

export interface StartOnboardingResponse {
  id: string;
  status: OnboardingSessionStatus;
  report: InspectionReport;
}

export interface SynthesizeSessionPayload {
  selected_tool_name: string;
  domain: string;
  capability_id: string;
  version?: string;
  estimated_cost_usd?: number;
  test_base_url?: string;
  production_base_url?: string;
}

export interface SynthesizeSessionResponse {
  id: string;
  status: OnboardingSessionStatus;
  synthesized_manifest: SynthesizedAction;
}

export interface RiskProposalResponse {
  id: string;
  status: OnboardingSessionStatus;
  risk_profile: { action: string; tier: number; reasoning: string }[];
}

export interface SandboxTestPayload {
  sample_input?: Record<string, unknown>;
  acknowledge_live_call?: boolean;
}

export interface SandboxTestResponse {
  id: string;
  status: OnboardingSessionStatus;
  sandbox_result: SandboxResult;
}

export interface ActivateSessionResponse {
  id: string;
  status: OnboardingSessionStatus;
  capability_id: string;
}

export interface ObsidianProjectionStatusResponse {
  status: string;
  targetDir: string;
  totalNotesCount: number;
  queueDepth: number;
  projectedEventsCount: number;
  lastProjectedAt: string | null;
  localRestApiEnabled: boolean;
}
