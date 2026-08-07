"use client";

import { LangGraphAgentWorkspace } from "@/components/jarvis/LangGraphAgentWorkspace";

export default function JarvisWorkspacePage() {
  return (
    <div className="space-y-6 pb-12">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Jarvis Universal Multi-Agent Command Console</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-purple/10 text-purple border border-purple/30">
              MOA &amp; LangGraph Engine
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Orchestrate Main Orchestrating Agent (MOA) intents, LangGraph technical agents, and executive copilot reasoning.
          </p>
        </div>
      </div>

      <LangGraphAgentWorkspace />
    </div>
  );
}

