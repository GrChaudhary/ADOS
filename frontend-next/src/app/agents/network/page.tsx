"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, AgentRegistryEntry, AgentStage, AgentTier, CreateAgentRequest, EventEnvelope } from "@/lib/api";
import { AGENTS, BUILTIN_AGENT_IDS, resolveAgentMeta } from "@/lib/agents";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STAGE_COLORS: Record<AgentStage, string> = {
  Perception: "emerald",
  Reasoning: "purple",
  CandidateGen: "amber",
  Evaluation: "pink",
  Execution: "teal",
  Learning: "indigo",
};

const STAGE_ICONS: Record<AgentStage, string> = {
  Perception: "👁️",
  Reasoning: "🧠",
  CandidateGen: "📦",
  Evaluation: "📊",
  Execution: "🚚",
  Learning: "🔄",
};

const STAGE_LABELS: Record<AgentStage, string> = {
  Perception: "Perception",
  Reasoning: "Reasoning / Root Cause",
  CandidateGen: "Candidate Generation",
  Evaluation: "Evaluation / Simulation",
  Execution: "Execution / ITSM",
  Learning: "Learning / Feedback",
};

const TIER_OPTIONS: AgentTier[] = [
  "Tier 0 (Autonomous)",
  "Tier 1 (Engineer Approval)",
  "Tier 2 (Multi-Executive)",
];

const TIER_COLORS: Record<AgentTier, string> = {
  "Tier 0 (Autonomous)": "emerald",
  "Tier 1 (Engineer Approval)": "amber",
  "Tier 2 (Multi-Executive)": "red",
};

const DEFAULT_TEMPLATES: Record<AgentStage, Partial<CreateAgentRequest>> = {
  Perception: {
    icon: "👁️", color: "emerald",
    model: "AOI Vision Engine",
    targetTier: "Tier 0 (Autonomous)",
    inputSchema: "Image Payload + Sensor Telemetry",
    outputSchema: "DefectEvent { defect_type, deviation_mm, confidence }",
    memoryRAG: false,
    instructions: "Analyze optical or sensor data to detect and classify manufacturing defects. Return structured findings with confidence.",
  },
  Reasoning: {
    icon: "🧠", color: "purple",
    model: "Bayesian Causal Reasoning Engine",
    targetTier: "Tier 0 (Autonomous)",
    inputSchema: "Defect Event + Historical Telemetry",
    outputSchema: "RootCause { condition_id, probability, evidence_chain }",
    memoryRAG: true,
    instructions: "Apply causal reasoning to isolate root cause. Use decision memory to weight evidence. Return probability-ranked conditions.",
  },
  CandidateGen: {
    icon: "📦", color: "amber",
    model: "Supply Chain & ERP Matcher",
    targetTier: "Tier 1 (Engineer Approval)",
    inputSchema: "Root Cause + Part Specification",
    outputSchema: "Candidates { option_id, description, estimated_cost, lead_time }",
    memoryRAG: true,
    instructions: "Generate resolution candidate options by querying ERP, supplier marketplaces, and parameter optimization models.",
  },
  Evaluation: {
    icon: "📊", color: "pink",
    model: "Monte Carlo Risk Simulator",
    targetTier: "Tier 1 (Engineer Approval)",
    inputSchema: "Resolution Candidates + Cost Rate",
    outputSchema: "RankedOptions { letter, score, downtime_min, cost_usd }",
    memoryRAG: true,
    instructions: "Simulate candidate options using Monte Carlo methods. Rank by cost, downtime, and quality risk. Return top 3 ranked options.",
  },
  Execution: {
    icon: "🚚", color: "teal",
    model: "ITSM / Logistics Router",
    targetTier: "Tier 2 (Multi-Executive)",
    inputSchema: "Approved Option + SLA Constraints",
    outputSchema: "ExecutionResult { action_taken, confirmation_id, eta }",
    memoryRAG: false,
    instructions: "Execute the approved resolution action via ITSM, logistics, or PLC systems. Confirm execution and return tracking ID.",
  },
  Learning: {
    icon: "🔄", color: "indigo",
    model: "Bayesian Recalibrator",
    targetTier: "Tier 0 (Autonomous)",
    inputSchema: "Resolved Incident Audit Trail",
    outputSchema: "WeightUpdate { edge_id, delta, new_weight, timestamp }",
    memoryRAG: true,
    instructions: "Process resolved incident outcomes to update causal model weights. Apply EMA smoothing to prevent overcorrection.",
  },
};

function buildEmptyForm(stage: AgentStage): CreateAgentRequest {
  return {
    label: "",
    description: "",
    ...DEFAULT_TEMPLATES[stage],
  } as CreateAgentRequest;
}

// ---------------------------------------------------------------------------
// Add Agent Modal
// ---------------------------------------------------------------------------

interface AddAgentModalProps {
  onClose: () => void;
  onCreated: (agent: AgentRegistryEntry) => void;
}

function AddAgentModal({ onClose, onCreated }: AddAgentModalProps) {
  const [step, setStep] = useState<"pick-stage" | "fill-form">("pick-stage");
  const [selectedStage, setSelectedStage] = useState<AgentStage | null>(null);
  const [form, setForm] = useState<CreateAgentRequest | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const queryClient = useQueryClient();
  const createMutation = useMutation({
    mutationFn: api.createAgent,
    onSuccess: (agent) => {
      queryClient.invalidateQueries({ queryKey: ["agents-registry"] });
      onCreated(agent);
      onClose();
    },
  });

  function pickStage(stage: AgentStage) {
    setSelectedStage(stage);
    setForm(buildEmptyForm(stage));
    setStep("fill-form");
  }

  function updateForm(field: keyof CreateAgentRequest, value: string | boolean) {
    setForm((prev) => prev ? { ...prev, [field]: value } : prev);
    setErrors((prev) => { const e = { ...prev }; delete e[field]; return e; });
  }

  function validate(): boolean {
    if (!form) return false;
    const e: Record<string, string> = {};
    if (!form.label || form.label.length < 2) e.label = "Label must be at least 2 characters.";
    if (!form.description || form.description.length < 10) e.description = "Description must be at least 10 characters.";
    if (!form.model || form.model.length < 2) e.model = "Model name is required.";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function submit() {
    if (!validate() || !form) return;
    createMutation.mutate(form);
  }

  const stageColor = selectedStage ? STAGE_COLORS[selectedStage] : "cobalt";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}>
      <div className="w-full max-w-2xl rounded-2xl bg-card border border-border-subtle shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-subtle bg-dark-900/80">
          <div className="flex items-center gap-3">
            <span className="text-xl">⚡</span>
            <div>
              <h2 className="text-base font-bold text-text-primary">Register Custom Agent</h2>
              <p className="text-xs text-text-secondary font-mono">
                {step === "pick-stage" ? "Step 1 of 2 — Choose manufacturing stage" : `Step 2 of 2 — Configure ${selectedStage} agent`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-text-secondary hover:text-text-primary text-lg transition-colors"
            id="add-agent-modal-close"
          >
            ✕
          </button>
        </div>

        {/* Step 1: Stage Picker */}
        {step === "pick-stage" && (
          <div className="p-6 space-y-4">
            <p className="text-xs text-text-secondary">
              Select the manufacturing pipeline stage this agent will operate in. Each stage has pre-filled defaults tailored for EV manufacturing operations.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {(Object.keys(STAGE_ICONS) as AgentStage[]).map((stage) => (
                <button
                  key={stage}
                  id={`stage-tile-${stage.toLowerCase()}`}
                  onClick={() => pickStage(stage)}
                  className="p-4 rounded-xl border border-border-subtle bg-dark-900/60 hover:border-cobalt hover:bg-cobalt/10 transition-all text-left space-y-2 group"
                >
                  <div className="text-2xl">{STAGE_ICONS[stage]}</div>
                  <div className="text-sm font-semibold text-text-primary group-hover:text-cobalt transition-colors">
                    {STAGE_LABELS[stage]}
                  </div>
                  <div className="text-[10px] font-mono text-text-secondary">{stage}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 2: Form */}
        {step === "fill-form" && form && selectedStage && (
          <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
            {/* Stage indicator */}
            <div className="flex items-center gap-2 p-2.5 rounded-lg bg-dark-900/60 border border-border-subtle text-xs font-mono">
              <span>{STAGE_ICONS[selectedStage]}</span>
              <span className="text-text-secondary">Stage:</span>
              <span className="text-text-primary font-semibold">{STAGE_LABELS[selectedStage]}</span>
              <button
                onClick={() => setStep("pick-stage")}
                className="ml-auto text-cobalt hover:underline text-[10px]"
              >
                ← Change
              </button>
            </div>

            {/* Label */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-text-secondary">Agent Label *</label>
              <input
                id="add-agent-label"
                type="text"
                value={form.label}
                onChange={(e) => updateForm("label", e.target.value)}
                placeholder="e.g. Weld Seam Inspector"
                className="w-full px-3 py-2 rounded-lg bg-dark-900/60 border border-border-subtle text-sm text-text-primary placeholder:text-text-secondary/50 focus:outline-none focus:border-cobalt transition-colors"
              />
              {errors.label && <p className="text-[10px] text-red-400">{errors.label}</p>}
            </div>

            {/* Description */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-text-secondary">Description *</label>
              <textarea
                id="add-agent-description"
                value={form.description}
                onChange={(e) => updateForm("description", e.target.value)}
                placeholder="Describe what this agent does in the manufacturing pipeline..."
                rows={3}
                className="w-full px-3 py-2 rounded-lg bg-dark-900/60 border border-border-subtle text-sm text-text-primary placeholder:text-text-secondary/50 focus:outline-none focus:border-cobalt transition-colors resize-none"
              />
              {errors.description && <p className="text-[10px] text-red-400">{errors.description}</p>}
            </div>

            {/* Model */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-text-secondary">AI Model / Engine *</label>
              <input
                id="add-agent-model"
                type="text"
                value={form.model}
                onChange={(e) => updateForm("model", e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-dark-900/60 border border-border-subtle text-sm text-text-primary placeholder:text-text-secondary/50 focus:outline-none focus:border-cobalt transition-colors"
              />
              {errors.model && <p className="text-[10px] text-red-400">{errors.model}</p>}
            </div>

            {/* Input / Output Schema side by side */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs font-mono text-text-secondary">Input Schema</label>
                <input
                  id="add-agent-input-schema"
                  type="text"
                  value={form.inputSchema}
                  onChange={(e) => updateForm("inputSchema", e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-dark-900/60 border border-border-subtle text-xs text-text-primary focus:outline-none focus:border-cobalt transition-colors"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-mono text-text-secondary">Output Schema</label>
                <input
                  id="add-agent-output-schema"
                  type="text"
                  value={form.outputSchema}
                  onChange={(e) => updateForm("outputSchema", e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-dark-900/60 border border-border-subtle text-xs text-text-primary focus:outline-none focus:border-cobalt transition-colors"
                />
              </div>
            </div>

            {/* Governance Tier */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-text-secondary">Governance Tier</label>
              <div className="flex gap-2 flex-wrap">
                {TIER_OPTIONS.map((tier) => (
                  <button
                    key={tier}
                    id={`tier-option-${tier.replace(/\s+/g, "-").toLowerCase()}`}
                    onClick={() => updateForm("targetTier", tier)}
                    className={`px-3 py-1.5 rounded-lg text-[11px] font-mono border transition-all ${
                      form.targetTier === tier
                        ? "bg-cobalt/20 border-cobalt text-cobalt font-semibold"
                        : "bg-dark-900/60 border-border-subtle text-text-secondary hover:border-border-accent"
                    }`}
                  >
                    {tier}
                  </button>
                ))}
              </div>
            </div>

            {/* Memory RAG toggle */}
            <div className="flex items-center justify-between p-3 rounded-lg bg-dark-900/60 border border-border-subtle">
              <div>
                <div className="text-xs font-mono text-text-primary font-semibold">Decision Memory RAG</div>
                <div className="text-[10px] text-text-secondary">Enable access to historical incident decision memory</div>
              </div>
              <button
                id="add-agent-memory-rag"
                onClick={() => updateForm("memoryRAG", !form.memoryRAG)}
                className={`relative w-10 h-5 rounded-full transition-colors ${form.memoryRAG ? "bg-emerald" : "bg-dark-900 border border-border-subtle"}`}
              >
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${form.memoryRAG ? "translate-x-5" : "translate-x-0.5"}`} />
              </button>
            </div>

            {/* Instructions (for ADK) */}
            <div className="space-y-1">
              <label className="text-xs font-mono text-text-secondary">
                System Instructions <span className="text-cobalt">(used by watsonx Orchestrate ADK)</span>
              </label>
              <textarea
                id="add-agent-instructions"
                value={form.instructions}
                onChange={(e) => updateForm("instructions", e.target.value)}
                rows={3}
                className="w-full px-3 py-2 rounded-lg bg-dark-900/60 border border-border-subtle text-xs text-text-primary placeholder:text-text-secondary/50 focus:outline-none focus:border-cobalt transition-colors resize-none font-mono"
              />
            </div>

            {/* Error from mutation */}
            {createMutation.isError && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-400">
                {String(createMutation.error)}
              </div>
            )}

            {/* Footer buttons */}
            <div className="flex justify-end gap-3 pt-2 border-t border-border-subtle">
              <button
                onClick={onClose}
                className="px-4 py-2 text-xs font-mono text-text-secondary hover:text-text-primary border border-border-subtle rounded-lg hover:border-border-accent transition-all"
              >
                Cancel
              </button>
              <button
                id="add-agent-submit"
                onClick={submit}
                disabled={createMutation.isPending}
                className="px-5 py-2 text-xs font-mono font-semibold rounded-lg bg-cobalt text-white hover:bg-cobalt/80 disabled:opacity-50 transition-all flex items-center gap-2"
              >
                {createMutation.isPending ? (
                  <><span className="animate-spin">⟳</span> Registering…</>
                ) : (
                  <>⚡ Register Agent</>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AgentNetworkPage() {
  const [activeTab, setActiveTab] = useState<"lineage" | "registry">("registry");
  const [selectedAgent, setSelectedAgent] = useState<AgentRegistryEntry | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const queryClient = useQueryClient();

  // Static fallback — always shown when backend is unreachable or errored
  const STATIC_FALLBACK: AgentRegistryEntry[] = Object.values(AGENTS).map((a) => ({
    ...a,
    targetTier: a.targetTier as AgentTier,
    stage: (
      a.id === "vision-spec-agent" || a.id === "cad-spec-agent" ? "Perception"
      : a.id === "causal-isolation-agent" ? "Reasoning"
      : a.id === "substitution-agent" || a.id === "parameter-adjustment-agent" ? "CandidateGen"
      : a.id === "impact-simulation-agent" ? "Evaluation"
      : a.id === "rerouting-agent" ? "Execution"
      : "Learning"
    ) as AgentStage,
    isBuiltIn: true,
    instructions: "",
    createdAt: "2025-01-01T00:00:00+00:00",
  }));

  // Live agent registry from backend (8 built-ins + custom from Cloudant)
  const agentsQuery = useQuery<AgentRegistryEntry[]>({
    queryKey: ["agents-registry"],
    queryFn: api.listAgents,
    staleTime: 30_000,
    retry: 1,
  });

  // Use backend data when available; fall back to static list on error or while loading
  const agents: AgentRegistryEntry[] =
    agentsQuery.data && agentsQuery.data.length > 0
      ? agentsQuery.data
      : STATIC_FALLBACK;

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: api.deleteAgent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agents-registry"] });
      if (selectedAgent && selectedAgent.id === deleteTarget) setSelectedAgent(null);
      setDeleteTarget(null);
    },
  });

  // Events for lineage tab
  const eventsQuery = useQuery<EventEnvelope[]>({
    queryKey: ["all-events-agent-swarm"],
    queryFn: () => api.listAllEvents(200),
    refetchInterval: 5000,
  });
  const events = eventsQuery.data ?? [];

  // Agent stats from events
  const agentStats: Record<string, { count: number; totalLatencyMs: number; totalConfidence: number; recentEvents: EventEnvelope[] }> = {};
  agents.forEach((a) => {
    agentStats[a.id] = { count: 0, totalLatencyMs: 0, totalConfidence: 0, recentEvents: [] };
  });
  events.forEach((evt) => {
    const payload = evt.payload ?? {};
    const agentId = (payload.agentId ?? payload.agent_id ?? evt.producedBy) as string;
    if (!agentId) return;
    const normalizedId = agentStats[agentId]
      ? agentId
      : agents.find((a) => a.id.toLowerCase().includes(agentId.toLowerCase()))?.id ?? agentId;
    if (!agentStats[normalizedId]) {
      agentStats[normalizedId] = { count: 0, totalLatencyMs: 0, totalConfidence: 0, recentEvents: [] };
    }
    const stats = agentStats[normalizedId];
    stats.count += 1;
    stats.totalLatencyMs += typeof payload.latencyMs === "number" ? payload.latencyMs : 120;
    stats.totalConfidence += typeof payload.confidence === "number" ? payload.confidence : 0.92;
    stats.recentEvents.push(evt);
  });

  // Derived counts
  const totalAgents = agents.length;
  const memoryRagCount = agents.filter((a) => a.memoryRAG).length;
  const customCount = agents.filter((a) => !a.isBuiltIn).length;

  return (
    <div className="space-y-6 pb-8">
      {/* Add Agent Modal */}
      {showAddModal && (
        <AddAgentModal
          onClose={() => setShowAddModal(false)}
          onCreated={(agent) => setSelectedAgent(agent)}
        />
      )}

      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Agent Swarm Runtime & Registry Studio</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-purple/10 text-purple border border-purple/30">
              {totalAgents} Active
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Enterprise AI specialist registry, model specifications, memory RAG permissions, and execution lineage.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* + Add Agent Button */}
          <button
            id="add-agent-btn"
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cobalt text-white text-xs font-mono font-semibold hover:bg-cobalt/80 transition-all shadow-lg hover:shadow-cobalt/20"
          >
            <span className="text-sm">+</span> Add Agent
          </button>

          {/* View Mode Switcher */}
          <div className="flex items-center gap-2 p-1 rounded-lg bg-dark-900/60 border border-border-subtle font-mono text-xs">
            <button
              onClick={() => setActiveTab("registry")}
              className={`px-3 py-1.5 rounded-md transition-all ${
                activeTab === "registry"
                  ? "bg-cobalt text-white font-semibold shadow"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              📋 Registry Catalog
            </button>
            <button
              onClick={() => setActiveTab("lineage")}
              className={`px-3 py-1.5 rounded-md transition-all ${
                activeTab === "lineage"
                  ? "bg-cobalt text-white font-semibold shadow"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              ⚡ Live Swarm & Lineage
            </button>
          </div>
        </div>
      </div>

      {/* TAB 1: AGENT REGISTRY CATALOG */}
      {activeTab === "registry" && (
        <div className="space-y-6">
          {/* Summary Badges */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle flex items-center gap-4">
              <span className="text-2xl p-3 rounded-lg bg-purple/10 text-purple border border-purple/20">🤖</span>
              <div>
                <div className="text-xs text-text-secondary">Registered Specialists</div>
                <div className="text-xl font-mono font-bold text-text-primary">{totalAgents} AI Agents</div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle flex items-center gap-4">
              <span className="text-2xl p-3 rounded-lg bg-emerald/10 text-emerald border border-emerald/20">🧠</span>
              <div>
                <div className="text-xs text-text-secondary">Memory RAG Enabled</div>
                <div className="text-xl font-mono font-bold text-emerald">{memoryRagCount} / {totalAgents} Agents</div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle flex items-center gap-4">
              <span className="text-2xl p-3 rounded-lg bg-cobalt/10 text-cobalt border border-cobalt/20">⚖️</span>
              <div>
                <div className="text-xs text-text-secondary">Governance Targets</div>
                <div className="text-xl font-mono font-bold text-cobalt">Tier 0 / 1 / 2</div>
              </div>
            </div>

            <div
              className="p-4 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle flex items-center gap-4 cursor-pointer hover:border-cobalt transition-all"
              onClick={() => setShowAddModal(true)}
            >
              <span className="text-2xl p-3 rounded-lg bg-amber/10 text-amber border border-amber/20">✨</span>
              <div>
                <div className="text-xs text-text-secondary">Custom Agents</div>
                <div className="text-xl font-mono font-bold text-amber">
                  {customCount} Added
                  {customCount === 0 && <span className="text-xs ml-1 text-text-secondary">→ Add one</span>}
                </div>
              </div>
            </div>
          </div>

          {/* Grid: Agent Cards + Detail Drawer */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left — Agent Card List */}
            <div className="lg:col-span-7 space-y-3">
              <div className="text-xs font-mono text-text-secondary flex justify-between items-center px-1">
                <span>SELECT AGENT TO INSPECT RUNTIME SPEC</span>
                <span>{totalAgents} / {totalAgents} Active</span>
              </div>

              {/* Loading state */}
              {agentsQuery.isLoading && (
                <div className="text-xs font-mono text-text-secondary text-center py-8 animate-pulse">
                  Loading agent registry…
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {agents.map((agent) => {
                  const isSelected = selectedAgent?.id === agent.id;
                  const isBuiltIn = BUILTIN_AGENT_IDS.has(agent.id);
                  const stats = agentStats[agent.id] ?? { count: 0, totalLatencyMs: 0, totalConfidence: 0 };
                  const avgLatency = stats.count > 0 ? (stats.totalLatencyMs / stats.count).toFixed(0) : "140";

                  return (
                    <div
                      key={agent.id}
                      onClick={() => setSelectedAgent(agent)}
                      className={`p-4 rounded-xl backdrop-blur-md border transition-all cursor-pointer space-y-2 ${
                        isSelected
                          ? "bg-cobalt/15 border-cobalt shadow-lg scale-[1.01]"
                          : "bg-card/60 border-border-subtle hover:border-border-accent hover:bg-card/80"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2.5">
                          <span className="text-xl">{agent.icon}</span>
                          <div>
                            <h3 className="text-sm font-semibold text-text-primary">{agent.label}</h3>
                            <div className="text-[10px] font-mono text-text-secondary">{agent.id}</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          {isBuiltIn ? (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-cobalt/20 text-cobalt font-bold">BUILT-IN 🔒</span>
                          ) : (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-amber/20 text-amber font-bold">CUSTOM ✨</span>
                          )}
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald/20 text-emerald font-bold">
                            ACTIVE 🟢
                          </span>
                        </div>
                      </div>

                      <p className="text-xs text-text-secondary line-clamp-2">{agent.description}</p>

                      <div className="flex items-center justify-between pt-2 border-t border-border-subtle text-[11px] font-mono text-text-secondary">
                        <span className="truncate max-w-[70%]">{agent.model}</span>
                        <span className="text-cobalt font-semibold">{avgLatency} ms</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right — Agent Runtime Inspector */}
            <div className="lg:col-span-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-5 shadow-lg">
              {selectedAgent ? (
                <>
                  <div className="flex items-center justify-between pb-4 border-b border-border-subtle">
                    <div className="flex items-center gap-3">
                      <span className="text-3xl">{selectedAgent.icon}</span>
                      <div>
                        <h2 className="text-lg font-bold text-text-primary">{selectedAgent.label}</h2>
                        <div className="text-xs font-mono text-cobalt">{selectedAgent.id}</div>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1.5">
                      <span className="px-2.5 py-1 rounded text-xs font-mono font-bold bg-purple/20 text-purple border border-purple/30">
                        {selectedAgent.targetTier}
                      </span>
                      {/* Delete button — only for custom agents */}
                      {!BUILTIN_AGENT_IDS.has(selectedAgent.id) && (
                        <button
                          id={`delete-agent-${selectedAgent.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (deleteTarget === selectedAgent.id) {
                              deleteMutation.mutate(selectedAgent.id);
                            } else {
                              setDeleteTarget(selectedAgent.id);
                            }
                          }}
                          disabled={deleteMutation.isPending}
                          className={`text-[10px] font-mono px-2 py-1 rounded border transition-all ${
                            deleteTarget === selectedAgent.id
                              ? "bg-red-500/20 border-red-500/50 text-red-400 animate-pulse"
                              : "bg-dark-900/60 border-border-subtle text-text-secondary hover:border-red-500/50 hover:text-red-400"
                          }`}
                        >
                          {deleteTarget === selectedAgent.id ? "⚠ Confirm Delete" : "🗑 Remove Agent"}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Stage Badge */}
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{STAGE_ICONS[selectedAgent.stage as AgentStage] ?? "🤖"}</span>
                    <span className="text-xs font-mono text-text-secondary">Stage:</span>
                    <span className="text-xs font-semibold text-text-primary">{STAGE_LABELS[selectedAgent.stage as AgentStage] ?? selectedAgent.stage}</span>
                  </div>

                  {/* Description */}
                  <div className="space-y-1">
                    <div className="text-xs font-mono text-text-secondary">Primary System Responsibility</div>
                    <p className="text-xs text-text-primary p-3 rounded-lg bg-dark-900/60 border border-border-subtle">
                      {selectedAgent.description}
                    </p>
                  </div>

                  {/* Model & Memory */}
                  <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                    <div className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle space-y-1">
                      <div className="text-text-secondary">AI Model Engine</div>
                      <div className="text-text-primary font-bold truncate">{selectedAgent.model}</div>
                    </div>
                    <div className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle space-y-1">
                      <div className="text-text-secondary">Memory RAG</div>
                      <div className={`font-bold ${selectedAgent.memoryRAG ? "text-emerald" : "text-text-secondary"}`}>
                        {selectedAgent.memoryRAG ? "ENABLED 🟢" : "DISABLED ⚪"}
                      </div>
                    </div>
                  </div>

                  {/* Input / Output Contracts */}
                  <div className="space-y-3 font-mono text-xs">
                    <div className="space-y-1">
                      <div className="text-text-secondary">Expected Input Contract:</div>
                      <div className="p-2.5 rounded bg-dark-900/60 border border-border-subtle text-[11px]">
                        {selectedAgent.inputSchema}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="text-text-secondary">Output Response Contract:</div>
                      <div className="p-2.5 rounded bg-dark-900/60 border border-border-subtle text-emerald text-[11px]">
                        {selectedAgent.outputSchema}
                      </div>
                    </div>
                  </div>

                  {/* Instructions (if present) */}
                  {selectedAgent.instructions && (
                    <div className="space-y-1 font-mono text-xs">
                      <div className="text-text-secondary">watsonx ADK Instructions:</div>
                      <div className="p-2.5 rounded bg-dark-900/60 border border-cobalt/20 text-cobalt text-[11px] leading-relaxed">
                        {selectedAgent.instructions}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center text-xs font-mono text-text-secondary py-12">
                  Select an agent from the left catalog to inspect runtime specifications.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: LIVE SWARM & LINEAGE */}
      {activeTab === "lineage" && (
        <div className="space-y-6">
          {/* Agent Swarm Cards Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {agents.map((agent) => {
              const stats = agentStats[agent.id] ?? { count: 0, totalLatencyMs: 0, totalConfidence: 0, recentEvents: [] };
              const avgLatency = stats.count > 0 ? (stats.totalLatencyMs / stats.count).toFixed(0) : "140";
              const avgConf = stats.count > 0 ? ((stats.totalConfidence / stats.count) * 100).toFixed(1) : "94.0";

              return (
                <div
                  key={agent.id}
                  className="p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle hover:border-border-accent transition-all space-y-3 shadow-lg"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <span className="text-2xl">{agent.icon}</span>
                      <div>
                        <h3 className="text-sm font-semibold text-text-primary">{agent.label}</h3>
                        <div className="text-[10px] font-mono text-text-secondary truncate max-w-[130px]">{agent.id}</div>
                      </div>
                    </div>
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald animate-pulse" />
                  </div>

                  <div className="grid grid-cols-2 gap-2 pt-2 border-t border-border-subtle text-xs font-mono">
                    <div className="p-2 rounded bg-dark-900/40 border border-border-subtle">
                      <div className="text-[10px] text-text-secondary">Avg Latency</div>
                      <div className="text-sm font-bold text-cobalt">{avgLatency} ms</div>
                    </div>
                    <div className="p-2 rounded bg-dark-900/40 border border-border-subtle">
                      <div className="text-[10px] text-text-secondary">Avg Confidence</div>
                      <div className="text-sm font-bold text-emerald">{avgConf}%</div>
                    </div>
                  </div>

                  <div className="flex justify-between items-center text-[11px] font-mono text-text-secondary pt-1">
                    <span>Invocations: {stats.count}</span>
                    <span className={agent.isBuiltIn ? "text-cobalt" : "text-amber"}>
                      {agent.isBuiltIn ? "Built-in" : "Custom"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Real-time Lineage Feed */}
          <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-lg">⚡</span>
                <h2 className="text-lg font-semibold text-text-primary">Agent Execution Lineage Log</h2>
              </div>
              <span className="text-xs font-mono text-cobalt px-2.5 py-1 rounded bg-cobalt/10 border border-cobalt/20">
                Recent {events.length} Events
              </span>
            </div>

            <div className="space-y-2 max-h-[450px] overflow-y-auto pr-1">
              {events.length === 0 ? (
                <div className="text-xs font-mono text-text-secondary py-8 text-center">
                  No recent agent events published. Trigger an incident on Line 2 to observe swarm execution.
                </div>
              ) : (
                events.map((evt) => {
                  const payload = evt.payload ?? {};
                  const rawAgentId = (payload.agentId ?? payload.agent_id ?? evt.producedBy) as string;
                  const agentMeta = resolveAgentMeta(rawAgentId);

                  return (
                    <div
                      key={evt.eventId}
                      className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-lg bg-dark-900/60 border border-border-subtle gap-2 text-xs font-mono"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-lg">{agentMeta.icon}</span>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-text-primary">{agentMeta.label}</span>
                            <span className="px-2 py-0.5 rounded text-[10px] bg-purple/10 text-purple border border-purple/30">
                              {evt.eventType}
                            </span>
                          </div>
                          <div className="text-[11px] text-text-secondary mt-0.5">
                            Incident: <span className="text-mono">{evt.incidentId}</span> | Produced by: {evt.producedBy}
                          </div>
                        </div>
                      </div>
                      <div className="text-right text-[11px] text-text-secondary">
                        <div>{new Date(evt.occurredAt).toLocaleTimeString()}</div>
                        {typeof payload.confidence === "number" && (
                          <div className="text-emerald font-semibold">
                            Conf: {(payload.confidence * 100).toFixed(1)}%
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
