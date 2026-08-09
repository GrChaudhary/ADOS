// Shared AI Specialist Agent metadata (documentation/03_Design_System.md
// section 4, documentation/05_Product_Bible.md section 3) - single source of
// truth used across Incident Workspace, Agent Swarm Network, and Agent Registry.
// Keys match the real agent_id strings published on AgentCompleted events
// (agents/sdk/base.py), e.g. "vision-spec-agent".

export interface AgentMeta {
  id: string;
  label: string;
  icon: string;
  color: string; // matches a --status-* CSS var name from globals.css
  description: string;
  model: string;
  inputSchema: string;
  outputSchema: string;
  memoryRAG: boolean;
  targetTier: "Tier 0 (Autonomous)" | "Tier 1 (Engineer Approval)" | "Tier 2 (Multi-Executive)";
}

export const AGENTS: Record<string, AgentMeta> = {
  "vision-spec-agent": {
    id: "vision-spec-agent",
    label: "Vision Spec",
    icon: "👁️",
    color: "emerald",
    description: "Processes AOI optical camera inspection images; isolates defect regions and computes bounding box vector coordinates.",
    model: "GPT-4o Vision / Custom AOI Engine",
    inputSchema: "Image Payload + Resolution Context",
    outputSchema: "BoundingBox2D { x, y, width, height, defect_class }",
    memoryRAG: false,
    targetTier: "Tier 0 (Autonomous)",
  },
  "cad-spec-agent": {
    id: "cad-spec-agent",
    label: "CAD Spec",
    icon: "📐",
    color: "cobalt",
    description: "Aligns 2D/3D defect scans against nominal STEP CAD files (.step) to measure micrometer tolerance offset vectors.",
    model: "CAD STEP Vector Alignment Engine",
    inputSchema: "STEP CAD Reference + Measured Offset Data",
    outputSchema: "MicrometerDeviation { axis, offset_mm, spec_limit }",
    memoryRAG: false,
    targetTier: "Tier 0 (Autonomous)",
  },
  "causal-isolation-agent": {
    id: "causal-isolation-agent",
    label: "Causal Isolation",
    icon: "🧠",
    color: "purple",
    description: "Evaluates Bayesian Causal Graph probabilistic edges to isolate primary root cause (tooling wear vs humidity vs raw material).",
    model: "Memory-Augmented Bayesian Causal Engine",
    inputSchema: "Defect Variance + Sensor Telemetry Logs",
    outputSchema: "CausalRootCause { condition_id, probability, evidence_chain }",
    memoryRAG: true,
    targetTier: "Tier 0 (Autonomous)",
  },
  "substitution-agent": {
    id: "substitution-agent",
    label: "Substitution",
    icon: "📦",
    color: "amber",
    description: "Queries local SAP ERP and external B2B supplier marketplaces to find alternative component inventory and stock lead times.",
    model: "B2B Supply Chain & SAP Inventory Matcher",
    inputSchema: "Part Specification + Required Lead Time",
    outputSchema: "SupplierMatch { supplier_id, available_units, lead_time_hrs, unit_cost }",
    memoryRAG: true,
    targetTier: "Tier 1 (Engineer Approval)",
  },
  "parameter-adjustment-agent": {
    id: "parameter-adjustment-agent",
    label: "Parameter Adjustment",
    icon: "⚙️",
    color: "cyan",
    description: "Calculates machine CNC spindle speed, feed rate, and coolant flow adjustments to offset minor tolerance drift.",
    model: "PLC Feed/Speed Optimization Engine",
    inputSchema: "CNC Telemetry + Micrometer Offset Vector",
    outputSchema: "MachineParameters { spindle_rpm, feed_rate_mm_min, coolant_bar }",
    memoryRAG: false,
    targetTier: "Tier 0 (Autonomous)",
  },
  "impact-simulation-agent": {
    id: "impact-simulation-agent",
    label: "Impact Simulation",
    icon: "📈",
    color: "pink",
    description: "Runs Monte Carlo pathway simulations comparing resolution options (Option A/B/C) across downtime, cost savings, and quality risk.",
    model: "Monte Carlo Financial & Risk Simulator",
    inputSchema: "Candidate Resolution Options + Downtime Cost Rate",
    outputSchema: "RankedOptions { Option A, Option B, Option C }",
    memoryRAG: true,
    targetTier: "Tier 1 (Engineer Approval)",
  },
  "rerouting-agent": {
    id: "rerouting-agent",
    label: "Rerouting",
    icon: "🚚",
    color: "teal",
    description: "Evaluates freight routes and logistics modes for urgent replacement part transport to Plant 04 Bangalore, Karnataka.",
    model: "Expedited Logistics Routing Engine",
    inputSchema: "Origin Hub + Destination Plant 04 + SLA Window",
    outputSchema: "LogisticsQuote { carrier, mode, transit_time_hrs, freight_cost }",
    memoryRAG: false,
    targetTier: "Tier 1 (Engineer Approval)",
  },
  "feedback-calibration-agent": {
    id: "feedback-calibration-agent",
    label: "Feedback Calibration",
    icon: "🔄",
    color: "indigo",
    description: "Replays completed incident audit trails to update Causal Graph edge weights via Bayesian & EMA updates.",
    model: "Self-Learning Bayesian Recalibrator",
    inputSchema: "IncidentRecord Outcome Audit Trail",
    outputSchema: "CausalWeightAdjustment { edge_id, delta, new_weight }",
    memoryRAG: true,
    targetTier: "Tier 0 (Autonomous)",
  },
  "watsonx-itsm-agent": {
    id: "watsonx-itsm-agent",
    label: "ITSM Execution",
    icon: "🎫",
    color: "teal",
    description: "Creates and looks up real ServiceNow incident records via a dedicated watsonx Orchestrate agent (ados_itsm_agent) against a live ServiceNow instance — the real system-of-record write for CreateIncident, CreateChangeRequest, ScheduleMaintenance, and NotifyOperator capability calls.",
    model: "watsonx Orchestrate Agent (groq/openai/gpt-oss-120b) — ServiceNow Table API",
    inputSchema: "CapabilityCall { capability, executionSteps, targetLineId, governance }",
    outputSchema: "ExecutionResult { ticket_id, status }",
    memoryRAG: false,
    targetTier: "Tier 1 (Engineer Approval)",
  },
  "prime-rlm-agent": {
    id: "prime-rlm-agent",
    label: "Prime RLM Agent",
    icon: "🧬",
    color: "purple",
    description: "Runs an analysis task inside a containerized Prime Agent, whose only tool is a persistent IPython kernel. Reasoning only: the sub-runtime is granted no ADOS capabilities, so it cannot act on the organization. Reaches ADOS solely through the governed MCP capability gateway.",
    model: "Prime Agent RLM Harness (Recursive Continual Learning)",
    inputSchema: "RLMTaskPrompt { prompt, domain, max_iterations }",
    outputSchema: "RLMExecutionResult { taskId, status, harness, kernelTrace }",
    memoryRAG: true,
    targetTier: "Tier 1 (Engineer Approval)",
  },
};


/** Set of IDs belonging to the 8 built-in agents — used to lock delete actions in the UI. */
export const BUILTIN_AGENT_IDS: ReadonlySet<string> = new Set(Object.keys(AGENTS));

export function resolveAgentMeta(agentId: string): AgentMeta {
  return (
    AGENTS[agentId] ?? {
      id: agentId,
      label: agentId || "Specialist Agent",
      icon: "🤖",
      color: "cobalt",
      description: "Specialist AI Agent",
      model: "Agentic AI Engine",
      inputSchema: "Typed Event Payload",
      outputSchema: "Capability Response Payload",
      memoryRAG: false,
      targetTier: "Tier 1 (Engineer Approval)",
    }
  );
}
