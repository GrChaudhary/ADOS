"use client";

import React, { useState } from "react";

interface JarvisSecretLabModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function JarvisSecretLabModal({ isOpen, onClose }: JarvisSecretLabModalProps) {
  const [activeTab, setActiveTab] = useState<"agents" | "telemetry" | "logs">("agents");
  const [promptInput, setPromptInput] = useState("");
  const [simulatedLogs, setSimulatedLogs] = useState<string[]>([
    "[SYSTEM_INIT] Jarvis Autonomous Engine L6 loaded successfully.",
    "[CAUSAL_GRAPH] 4,280 historical precedent vectors indexed in Cloudant NoSQL.",
    "[WATSONX_ITSM] IBM IAM bearer token active • Latency 42ms.",
    "[DIGITAL_TWIN] CNC Spindle vibration telemetry streaming (0.18 mm/s).",
  ]);

  if (!isOpen) return null;

  const handleRunCommand = (e: React.FormEvent) => {
    e.preventDefault();
    if (!promptInput.trim()) return;
    const newLog = `[OPERATOR_COMMAND] ${promptInput} -> Processing via Jarvis Causal AI Agent SDK...`;
    const responseLog = `[JARVIS_AI] Recommendation: Execute Tier-0 autonomous parameter shift (+0.05mm tolerance). Confidence 98.4%.`;
    setSimulatedLogs((prev) => [...prev, newLog, responseLog]);
    setPromptInput("");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-4xl max-h-[90vh] overflow-hidden rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 text-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-8 py-6 border-b border-purple-500/20 bg-purple-950/30">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-pink-500 to-purple-600 flex items-center justify-center font-orbitron font-bold text-white shadow-lg shadow-pink-500/30">
              J
            </div>
            <div>
              <h2 className="text-xl font-orbitron font-bold jarvis-gradient-text tracking-wide">
                JARVIS SECRET LAB
              </h2>
              <p className="text-xs text-purple-300/70 font-mono">
                L6 Executive Intelligence & Causal Recalibration Engine
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-10 h-10 rounded-full bg-white/5 hover:bg-white/10 text-purple-200 hover:text-white flex items-center justify-center transition-colors font-mono"
          >
            ✕
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-purple-500/20 px-8 bg-black/20">
          <button
            onClick={() => setActiveTab("agents")}
            className={`py-3 px-5 font-orbitron text-xs tracking-wider transition-colors border-b-2 ${
              activeTab === "agents"
                ? "border-pink-500 text-pink-400 font-bold"
                : "border-transparent text-purple-300/60 hover:text-purple-200"
            }`}
          >
            SPECIALIST AI AGENTS
          </button>
          <button
            onClick={() => setActiveTab("telemetry")}
            className={`py-3 px-5 font-orbitron text-xs tracking-wider transition-colors border-b-2 ${
              activeTab === "telemetry"
                ? "border-pink-500 text-pink-400 font-bold"
                : "border-transparent text-purple-300/60 hover:text-purple-200"
            }`}
          >
            DIGITAL TWIN TELEMETRY
          </button>
          <button
            onClick={() => setActiveTab("logs")}
            className={`py-3 px-5 font-orbitron text-xs tracking-wider transition-colors border-b-2 ${
              activeTab === "logs"
                ? "border-pink-500 text-pink-400 font-bold"
                : "border-transparent text-purple-300/60 hover:text-purple-200"
            }`}
          >
            NEURAL LOG CONSOLE
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 p-8 overflow-y-auto space-y-6">
          {activeTab === "agents" && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[
                {
                  name: "VisionSpecAgent",
                  desc: "Analyzes surface micro-cracks & thermal imaging anomalies.",
                  status: "ACTIVE • 99.8%",
                  color: "from-pink-500/20 to-purple-500/20 border-pink-500/30",
                },
                {
                  name: "CausalIsolationAgent",
                  desc: "Isolates root cause variables using Bayesian causal networks.",
                  status: "ACTIVE • 98.9%",
                  color: "from-purple-500/20 to-indigo-500/20 border-purple-500/30",
                },
                {
                  name: "CADSpecAgent",
                  desc: "Cross-references STEP 3D CAD files against tolerance specs.",
                  status: "ACTIVE • 100%",
                  color: "from-cyan-500/20 to-blue-500/20 border-cyan-500/30",
                },
                {
                  name: "SubstitutionAgent",
                  desc: "Queries Cloudant & SAP inventory for soft-lock part swaps.",
                  status: "STANDBY • READY",
                  color: "from-emerald-500/20 to-teal-500/20 border-emerald-500/30",
                },
              ].map((agent, idx) => (
                <div
                  key={idx}
                  className={`p-5 rounded-2xl bg-gradient-to-br ${agent.color} border backdrop-blur-md flex flex-col justify-between hover:scale-[1.02] transition-transform`}
                >
                  <div>
                    <div className="flex justify-between items-center mb-2">
                      <h4 className="font-orbitron font-bold text-sm text-white">{agent.name}</h4>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-pink-500/20 text-pink-300 border border-pink-500/40">
                        {agent.status}
                      </span>
                    </div>
                    <p className="text-xs text-purple-200/70">{agent.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === "telemetry" && (
            <div className="space-y-4">
              <div className="p-6 rounded-2xl bg-purple-950/40 border border-purple-500/30 flex justify-between items-center">
                <div>
                  <h4 className="text-sm font-orbitron font-bold text-white mb-1">
                    CNC Spindle Vibration Telemetry
                  </h4>
                  <p className="text-xs text-purple-300/70 font-mono">Line 4 • Sensor #8841</p>
                </div>
                <div className="text-right">
                  <span className="text-xl font-orbitron text-cyan-400 font-bold">0.18 mm/s</span>
                  <p className="text-[10px] text-emerald-400 font-mono">OPTIMAL</p>
                </div>
              </div>
              <div className="p-6 rounded-2xl bg-purple-950/40 border border-purple-500/30 flex justify-between items-center">
                <div>
                  <h4 className="text-sm font-orbitron font-bold text-white mb-1">
                    IBM watsonx ITSM Hub Connector
                  </h4>
                  <p className="text-xs text-purple-300/70 font-mono">IAM Authenticated • OAuth 2.0</p>
                </div>
                <div className="text-right">
                  <span className="text-xl font-orbitron text-pink-400 font-bold">42 ms</span>
                  <p className="text-[10px] text-emerald-400 font-mono">CONNECTED</p>
                </div>
              </div>
            </div>
          )}

          {activeTab === "logs" && (
            <div className="rounded-2xl bg-black/60 p-5 border border-purple-500/20 font-mono text-xs space-y-2 h-64 overflow-y-auto text-purple-200">
              {simulatedLogs.map((log, i) => (
                <div key={i} className="leading-relaxed">
                  <span className="text-pink-400">&gt;</span> {log}
                </div>
              ))}
            </div>
          )}

          {/* Interactive Command Input */}
          <form onSubmit={handleRunCommand} className="flex gap-3">
            <input
              type="text"
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              placeholder="Ask Jarvis Secret Lab Copilot (e.g. 'Optimize yield for Line 2')..."
              className="flex-1 px-5 py-3 rounded-xl bg-purple-950/50 border border-purple-500/30 text-white placeholder-purple-300/40 focus:outline-none focus:border-pink-500 font-mono text-xs"
            />
            <button
              type="submit"
              className="px-6 py-3 rounded-xl jarvis-btn-primary font-orbitron font-bold text-xs tracking-wider text-white shadow-lg"
            >
              EXECUTE
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
