// Shared AI Specialist Agent metadata (documentation/03_Design_System.md
// section 4, documentation/05_Product_Bible.md section 3) - one source of
// truth used by the Incident Workspace's live event tabs (this phase) and
// the Agent Swarm Network view (Phase 5B). Keys match the real agent_id
// strings published on AgentCompleted events (agents/sdk/base.py), e.g.
// "vision-spec-agent".

export interface AgentMeta {
  id: string;
  label: string;
  icon: string;
  color: string; // matches a --status-* CSS var name from globals.css
}

export const AGENTS: Record<string, AgentMeta> = {
  "vision-spec-agent": { id: "vision-spec-agent", label: "Vision Spec", icon: "\u{1F441}️", color: "emerald" },
  "cad-spec-agent": { id: "cad-spec-agent", label: "CAD Spec", icon: "\u{1F4D0}", color: "cobalt" },
  "causal-isolation-agent": { id: "causal-isolation-agent", label: "Causal Isolation", icon: "\u{1F9E0}", color: "purple" },
  "substitution-agent": { id: "substitution-agent", label: "Substitution", icon: "\u{1F4E6}", color: "amber" },
  "parameter-adjustment-agent": { id: "parameter-adjustment-agent", label: "Parameter Adjustment", icon: "⚙️", color: "cyan" },
  "impact-simulation-agent": { id: "impact-simulation-agent", label: "Impact Simulation", icon: "\u{1F4C8}", color: "pink" },
  "rerouting-agent": { id: "rerouting-agent", label: "Rerouting", icon: "\u{1F69A}", color: "teal" },
  "feedback-calibration-agent": { id: "feedback-calibration-agent", label: "Feedback Calibration", icon: "\u{1F504}", color: "indigo" },
};

export function resolveAgentMeta(agentId: string): AgentMeta {
  return (
    AGENTS[agentId] ?? {
      id: agentId,
      label: agentId || "Specialist Agent",
      icon: "\u{1F916}",
      color: "cobalt",
    }
  );
}
