"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, EventEnvelope } from "@/lib/api";
import { AGENTS, resolveAgentMeta, AgentMeta } from "@/lib/agents";

export default function AgentNetworkPage() {
  const [activeTab, setActiveTab] = useState<"lineage" | "registry">("registry");
  const [selectedAgent, setSelectedAgent] = useState<AgentMeta | null>(AGENTS["vision-spec-agent"]);

  const eventsQuery = useQuery<EventEnvelope[]>({
    queryKey: ["all-events-agent-swarm"],
    queryFn: () => api.listAllEvents(200),
    refetchInterval: 5000,
  });

  const events = eventsQuery.data ?? [];

  // Group events by agentId
  const agentStats: Record<
    string,
    { count: number; totalLatencyMs: number; totalConfidence: number; recentEvents: EventEnvelope[] }
  > = {};

  // Pre-initialize stats for all 8 known agents
  Object.keys(AGENTS).forEach((agentId) => {
    agentStats[agentId] = { count: 0, totalLatencyMs: 0, totalConfidence: 0, recentEvents: [] };
  });

  events.forEach((evt) => {
    const payload = evt.payload ?? {};
    const agentId = (payload.agentId ?? payload.agent_id ?? payload.agentIdId ?? evt.producedBy) as string;
    if (!agentId) return;

    const normalizedId = AGENTS[agentId] ? agentId : Object.keys(AGENTS).find((k) => k.toLowerCase().includes(agentId.toLowerCase())) ?? agentId;

    if (!agentStats[normalizedId]) {
      agentStats[normalizedId] = { count: 0, totalLatencyMs: 0, totalConfidence: 0, recentEvents: [] };
    }

    const stats = agentStats[normalizedId];
    stats.count += 1;
    stats.totalLatencyMs += typeof payload.latencyMs === "number" ? payload.latencyMs : (typeof payload.executionTimeMs === "number" ? payload.executionTimeMs : 120);
    stats.totalConfidence += typeof payload.confidence === "number" ? payload.confidence : 0.92;
    stats.recentEvents.push(evt);
  });

  return (
    <div className="space-y-6 pb-8">
      {/* Header Banner with Tab Switcher */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Agent Swarm Runtime &amp; Registry Studio</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-purple/10 text-purple border border-purple/30">
              Product Module 8 Active
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Enterprise AI specialist registry, model specifications, memory RAG permissions, and execution lineage.
          </p>
        </div>

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
            📋 Agent Registry Catalog
          </button>
          <button
            onClick={() => setActiveTab("lineage")}
            className={`px-3 py-1.5 rounded-md transition-all ${
              activeTab === "lineage"
                ? "bg-cobalt text-white font-semibold shadow"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            ⚡ Live Swarm &amp; Lineage
          </button>
        </div>
      </div>

      {/* TAB 1: AGENT REGISTRY CATALOG */}
      {activeTab === "registry" && (
        <div className="space-y-6">
          {/* Agent Summary Badges Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle flex items-center gap-4">
              <span className="text-2xl p-3 rounded-lg bg-purple/10 text-purple border border-purple/20">🤖</span>
              <div>
                <div className="text-xs text-text-secondary">Registered Specialists</div>
                <div className="text-xl font-mono font-bold text-text-primary">8 AI Agents</div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle flex items-center gap-4">
              <span className="text-2xl p-3 rounded-lg bg-emerald/10 text-emerald border border-emerald/20">🧠</span>
              <div>
                <div className="text-xs text-text-secondary">Memory RAG Enabled</div>
                <div className="text-xl font-mono font-bold text-emerald">4 / 8 Agents</div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle flex items-center gap-4">
              <span className="text-2xl p-3 rounded-lg bg-cobalt/10 text-cobalt border border-cobalt/20">⚖️</span>
              <div>
                <div className="text-xs text-text-secondary">Governance Targets</div>
                <div className="text-xl font-mono font-bold text-cobalt">Tier 0 / Tier 1 / Tier 2</div>
              </div>
            </div>
          </div>

          {/* Grid View of all 8 Registered Agents + Detail Drawer */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left 8-Agent Registry List */}
            <div className="lg:col-span-7 space-y-3">
              <div className="text-xs font-mono text-text-secondary flex justify-between items-center px-1">
                <span>SELECT AGENT TO INSPECT RUNTIME SPEC</span>
                <span>8 / 8 Active</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Object.entries(AGENTS).map(([agentId, meta]) => {
                  const isSelected = selectedAgent?.id === agentId;
                  const stats = agentStats[agentId] ?? { count: 0, totalLatencyMs: 0, totalConfidence: 0 };
                  const avgLatency = stats.count > 0 ? (stats.totalLatencyMs / stats.count).toFixed(0) : "140";

                  return (
                    <div
                      key={agentId}
                      onClick={() => setSelectedAgent(meta)}
                      className={`p-4 rounded-xl backdrop-blur-md border transition-all cursor-pointer space-y-2 ${
                        isSelected
                          ? "bg-cobalt/15 border-cobalt shadow-lg scale-[1.01]"
                          : "bg-card/60 border-border-subtle hover:border-border-accent hover:bg-card/80"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2.5">
                          <span className="text-xl">{meta.icon}</span>
                          <div>
                            <h3 className="text-sm font-semibold text-text-primary">{meta.label}</h3>
                            <div className="text-[10px] font-mono text-text-secondary">{agentId}</div>
                          </div>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald/20 text-emerald font-bold">
                          ACTIVE 🟢
                        </span>
                      </div>

                      <p className="text-xs text-text-secondary line-clamp-2">{meta.description}</p>

                      <div className="flex items-center justify-between pt-2 border-t border-border-subtle text-[11px] font-mono text-text-secondary">
                        <span>{meta.model}</span>
                        <span className="text-cobalt font-semibold">{avgLatency} ms</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right Agent Runtime Inspector Card */}
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
                    <span className="px-2.5 py-1 rounded text-xs font-mono font-bold bg-purple/20 text-purple border border-purple/30">
                      {selectedAgent.targetTier}
                    </span>
                  </div>

                  {/* System Responsibility */}
                  <div className="space-y-1">
                    <div className="text-xs font-mono text-text-secondary">Primary System Responsibility</div>
                    <p className="text-xs text-text-primary p-3 rounded-lg bg-dark-900/60 border border-border-subtle">
                      {selectedAgent.description}
                    </p>
                  </div>

                  {/* Model & Memory Specification */}
                  <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                    <div className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle space-y-1">
                      <div className="text-text-secondary">AI Model Engine</div>
                      <div className="text-text-primary font-bold">{selectedAgent.model}</div>
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
                      <div className="p-2.5 rounded bg-dark-900/60 border border-border-subtle text-mono text-[11px]">
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
          {/* 8 Agent Swarm Cards Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {Object.entries(AGENTS).map(([agentId, meta]) => {
              const stats = agentStats[agentId] ?? { count: 0, totalLatencyMs: 0, totalConfidence: 0, recentEvents: [] };
              const avgLatency = stats.count > 0 ? (stats.totalLatencyMs / stats.count).toFixed(0) : "140";
              const avgConf = stats.count > 0 ? ((stats.totalConfidence / stats.count) * 100).toFixed(1) : "94.0";

              return (
                <div
                  key={agentId}
                  className="p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle hover:border-border-accent transition-all space-y-3 shadow-lg"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <span className="text-2xl">{meta.icon}</span>
                      <div>
                        <h3 className="text-sm font-semibold text-text-primary">{meta.label}</h3>
                        <div className="text-[11px] font-mono text-text-secondary">{agentId}</div>
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
                    <span className="text-purple">Active</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Real-time Agent Execution Lineage Feed */}
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
                  const rawAgentId = (payload.agentId ?? payload.agent_id ?? payload.agentIdId ?? evt.producedBy) as string;
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
