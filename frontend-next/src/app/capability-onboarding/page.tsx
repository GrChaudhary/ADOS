"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  api,
  OnboardingSession,
  OnboardingSessionStatus,
  OnboardingTrack,
  DiscoveredTool,
  AuditLogEntry,
} from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";
import { useCurrentUser } from "@/lib/useCurrentUser";

// Static badge classes to avoid Tailwind purge bugs
const STATUS_BADGES: Record<OnboardingSessionStatus, string> = {
  submitted: "bg-purple/20 text-purple border-purple/30",
  inspected: "bg-cobalt/20 text-cobalt border-cobalt/30",
  synthesized: "bg-amber/20 text-amber border-amber/30",
  risk_reviewed: "bg-cyan/20 text-cyan border-cyan/30",
  sandbox_tested: "bg-pink/20 text-pink border-pink/30",
  activated: "bg-emerald/20 text-emerald border-emerald/30",
  failed: "bg-status-red/20 text-status-red border-status-red/30",
  aborted: "bg-glass text-text-secondary border-border-subtle",
};

function getTurnNumber(status: OnboardingSessionStatus): number {
  switch (status) {
    case "submitted":
      return 1;
    case "inspected":
      return 2;
    case "synthesized":
      return 3;
    case "risk_reviewed":
      return 4;
    case "sandbox_tested":
      return 5;
    case "activated":
      return 6; // completed
    default:
      return 1;
  }
}

export default function CapabilityOnboardingPage() {
  const hasToken = useHasToken();
  const currentUser = useCurrentUser();
  const queryClient = useQueryClient();

  const canGovern = currentUser?.role === "admin" || currentUser?.role === "executive";

  const [activeTab, setActiveTab] = useState<"wizard" | "history">("wizard");
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [selectedAuditSession, setSelectedAuditSession] = useState<OnboardingSession | null>(null);

  // Turn 1 Form State
  const [sourceUrl, setSourceUrl] = useState("tests/fixtures/mcp_native_sample/");
  const [trackHint, setTrackHint] = useState<OnboardingTrack | "auto">("auto");
  const [turn1Error, setTurn1Error] = useState<string | null>(null);

  // Turn 2 Form State
  const [selectedToolName, setSelectedToolName] = useState<string>("");
  const [domain, setDomain] = useState<string>("it");
  const [capabilityId, setCapabilityId] = useState<string>("");
  const [version, setVersion] = useState<string>("1.0.0");
  const [estimatedCostUsd, setEstimatedCostUsd] = useState<number>(0.0);
  const [testBaseUrl, setTestBaseUrl] = useState<string>("");
  const [productionBaseUrl, setProductionBaseUrl] = useState<string>("");
  const [turn2Error, setTurn2Error] = useState<string | null>(null);
  const [expandedSchemaTool, setExpandedSchemaTool] = useState<string | null>(null);

  // Turn 4 Form State
  const [sampleInputJson, setSampleInputJson] = useState<string>("{\n  \n}");
  const [acknowledgeLiveCall, setAcknowledgeLiveCall] = useState<boolean>(false);
  const [turn4Error, setTurn4Error] = useState<string | null>(null);
  const [showRawOutput, setShowRawOutput] = useState<boolean>(false);

  // Queries
  const sessionsQuery = useQuery<OnboardingSession[]>({
    queryKey: ["onboarding-sessions"],
    queryFn: api.getOnboardingSessions,
    enabled: hasToken,
    refetchInterval: 5000,
  });

  const activeSessionQuery = useQuery<OnboardingSession>({
    queryKey: ["onboarding-session", currentSessionId],
    queryFn: () => api.getOnboardingSession(currentSessionId!),
    enabled: hasToken && !!currentSessionId,
    refetchInterval: 3000,
  });

  const session = activeSessionQuery.data;

  // Sync state when session changes
  useEffect(() => {
    if (session?.inspection_report?.tools?.length && !selectedToolName) {
      const firstTool = session.inspection_report.tools[0];
      setSelectedToolName(firstTool.name);
      setCapabilityId(firstTool.name.replace(/[^a-zA-Z0-9]/g, ""));
    }
  }, [session, selectedToolName]);

  // Mutations
  const invalidateSessions = () => {
    queryClient.invalidateQueries({ queryKey: ["onboarding-sessions"] });
    if (currentSessionId) {
      queryClient.invalidateQueries({ queryKey: ["onboarding-session", currentSessionId] });
    }
  };

  const startMutation = useMutation({
    mutationFn: api.startOnboardingSession,
    onSuccess: (res) => {
      setTurn1Error(null);
      setCurrentSessionId(res.id);
      invalidateSessions();
    },
    onError: (err: any) => {
      setTurn1Error(err?.message || "Inspection failed.");
      invalidateSessions();
    },
  });

  const synthesizeMutation = useMutation({
    mutationFn: api.synthesizeOnboardingSession,
    onSuccess: () => {
      setTurn2Error(null);
      invalidateSessions();
    },
    onError: (err: any) => {
      setTurn2Error(err?.message || "Synthesis failed.");
      invalidateSessions();
    },
  });

  const riskProposalMutation = useMutation({
    mutationFn: api.proposeRiskOnboardingSession,
    onSuccess: () => {
      invalidateSessions();
    },
    onError: (err: any) => {
      if (err?.message?.includes("409")) {
        invalidateSessions();
      }
    },
  });

  const sandboxTestMutation = useMutation({
    mutationFn: api.sandboxTestOnboardingSession,
    onSuccess: () => {
      setTurn4Error(null);
      invalidateSessions();
    },
    onError: (err: any) => {
      const msg = err?.message || "Sandbox test failed.";
      const cleanMsg = msg.replace(/^\d+\s+\/api\/backend[^\:]*:\s*/, "");
      setTurn4Error(cleanMsg);
      invalidateSessions();
    },
  });

  const activateMutation = useMutation({
    mutationFn: api.activateOnboardingSession,
    onSuccess: () => {
      invalidateSessions();
      queryClient.invalidateQueries({ queryKey: ["capability-manifests"] });
    },
    onError: () => {
      invalidateSessions();
    },
  });

  function handleStartTurn1() {
    if (!sourceUrl.trim()) return;
    setTurn1Error(null);
    startMutation.mutate({
      source_url: sourceUrl.trim(),
      track_hint: trackHint === "auto" ? undefined : trackHint,
    });
  }

  function handleSynthesizeTurn2() {
    if (!currentSessionId || !selectedToolName || !domain.trim() || !capabilityId.trim()) return;
    setTurn2Error(null);
    synthesizeMutation.mutate({
      id: currentSessionId,
      payload: {
        selected_tool_name: selectedToolName,
        domain: domain.trim(),
        capability_id: capabilityId.trim(),
        version: version.trim() || "1.0.0",
        estimated_cost_usd: estimatedCostUsd || 0,
        test_base_url: testBaseUrl.trim() || undefined,
        production_base_url: productionBaseUrl.trim() || undefined,
      },
    });
  }

  function handleRiskProposalTurn3() {
    if (!currentSessionId) return;
    riskProposalMutation.mutate(currentSessionId);
  }

  function handleSandboxTestTurn4() {
    if (!currentSessionId) return;
    let parsedInput: Record<string, unknown> = {};
    try {
      if (sampleInputJson.trim()) {
        parsedInput = JSON.parse(sampleInputJson);
      }
    } catch {
      setTurn4Error("Invalid JSON input syntax. Please check formatting.");
      return;
    }

    setTurn4Error(null);
    sandboxTestMutation.mutate({
      id: currentSessionId,
      payload: {
        sample_input: parsedInput,
        acknowledge_live_call: acknowledgeLiveCall,
      },
    });
  }

  function handleActivateTurn5() {
    if (!currentSessionId) return;
    activateMutation.mutate(currentSessionId);
  }

  function startNewSession() {
    setCurrentSessionId(null);
    setTurn1Error(null);
    setTurn2Error(null);
    setTurn4Error(null);
    setSelectedToolName("");
    setCapabilityId("");
  }

  const currentTurn = session ? getTurnNumber(session.status) : 1;

  return (
    <div className="space-y-8 pb-16">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">BYOC Studio</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-purple/20 text-purple border border-purple/40 font-semibold">
              Phase 7 — Capability Onboarding
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Governed 5-turn onboarding pipeline for MCP-native tools and OpenAPI services into the MOA execution substrate.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="px-3 py-1.5 rounded-lg bg-glass border border-border-subtle text-xs font-mono text-text-secondary flex items-center gap-2">
            <span>Governance Role:</span>
            {currentUser ? (
              <span className={canGovern ? "text-emerald font-bold" : "text-amber font-bold"}>
                {currentUser.displayName} ({currentUser.role.toUpperCase()})
              </span>
            ) : (
              <span className="text-text-secondary font-bold">Anonymous</span>
            )}
          </div>

          <Link
            href="/integrations"
            className="px-3.5 py-2 rounded-xl text-xs font-mono bg-cobalt/20 text-cobalt border border-cobalt/40 hover:bg-cobalt/30 transition-all"
          >
            ← Integrations Hub
          </Link>
        </div>
      </div>

      {!hasToken && (
        <div className="p-4 rounded-xl bg-status-red/10 border border-status-red/30 text-status-red text-sm font-mono">
          ⚠️ Service Token Required. Please enter a valid service token in Settings or header to use BYOC Studio.
        </div>
      )}

      {hasToken && !canGovern && (
        <div className="p-4 rounded-xl bg-amber/10 border border-amber/30 text-amber text-xs font-mono">
          ℹ️ Your current role ({currentUser?.role ?? "viewer"}) permits read-only viewing of sessions. Mutating actions require <code className="font-bold">ADMIN</code> or <code className="font-bold">EXECUTIVE</code> privileges.
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="flex items-center justify-between border-b border-purple-500/20 pb-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setActiveTab("wizard")}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
              activeTab === "wizard"
                ? "bg-purple-600/30 text-white border border-purple-400/50 shadow-lg shadow-purple-500/10 font-bold"
                : "text-text-secondary hover:text-white hover:bg-purple-950/30"
            }`}
          >
            🚀 Wizard Studio {session && <span className="ml-1 text-xs opacity-75">({session.id.slice(0, 8)})</span>}
          </button>
          <button
            onClick={() => setActiveTab("history")}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
              activeTab === "history"
                ? "bg-purple-600/30 text-white border border-purple-400/50 shadow-lg shadow-purple-500/10 font-bold"
                : "text-text-secondary hover:text-white hover:bg-purple-950/30"
            }`}
          >
            📜 Session History &amp; Audit Logs ({sessionsQuery.data?.length ?? 0})
          </button>
        </div>

        {currentSessionId && (
          <button
            onClick={startNewSession}
            className="px-3 py-1.5 rounded-lg text-xs font-mono bg-glass border border-border-subtle hover:border-purple-400 text-text-secondary hover:text-text-primary transition-all"
          >
            + Start New Session
          </button>
        )}
      </div>

      {/* WIZARD STUDIO TAB */}
      {activeTab === "wizard" && (
        <div className="space-y-8">
          {/* Step Progress Tracker */}
          <div className="p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-xl">
            <div className="grid grid-cols-5 gap-2 text-center text-xs font-mono">
              {[
                { turn: 1, label: "1. Inspect", key: "inspected" },
                { turn: 2, label: "2. Synthesize", key: "synthesized" },
                { turn: 3, label: "3. Risk Review", key: "risk_reviewed" },
                { turn: 4, label: "4. Sandbox Test", key: "sandbox_tested" },
                { turn: 5, label: "5. Activate", key: "activated" },
              ].map((step) => {
                const isPassed = session ? currentTurn > step.turn : false;
                const isCurrent = session ? currentTurn === step.turn : step.turn === 1;

                return (
                  <div
                    key={step.turn}
                    className={`p-3 rounded-xl border transition-all ${
                      isCurrent
                        ? "bg-purple-600/20 border-purple-400 text-white font-bold shadow-lg shadow-purple-500/10"
                        : isPassed
                        ? "bg-emerald/10 border-emerald/30 text-emerald"
                        : "bg-glass border-border-subtle text-text-secondary opacity-60"
                    }`}
                  >
                    <div>{step.label}</div>
                    {isPassed && <div className="text-[10px] text-emerald mt-1 font-bold">✓ PASSED</div>}
                    {isCurrent && session && (
                      <div className="text-[10px] text-purple-300 mt-1 uppercase tracking-wider font-bold">
                        {session.status}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* TURN 1: INSPECT */}
          {(!session || session.status === "submitted" || (session.status === "failed" && !session.inspection_report)) && (
            <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">🔍</span>
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Turn 1 — Inspect Repository / Specification</h2>
                    <p className="text-xs text-text-secondary">
                      Provide a GitHub repo URL or local path. The inspector will auto-detect MCP-native or OpenAPI tools.
                    </p>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded text-xs font-mono bg-purple/20 text-purple border border-purple/30 font-semibold">
                  Turn 1 of 5
                </span>
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary">Source URL / Local Fixture Path *</label>
                  <input
                    type="text"
                    value={sourceUrl}
                    onChange={(e) => setSourceUrl(e.target.value)}
                    placeholder="e.g. https://github.com/my-org/mcp-server or tests/fixtures/mcp_native_sample/"
                    className="w-full rounded-xl border border-border-subtle bg-glass px-4 py-3 text-sm text-text-primary focus:border-purple-400 outline-none font-mono"
                  />
                  <p className="text-[11px] text-text-secondary">
                    Local fixture option available: <code className="text-cobalt">tests/fixtures/mcp_native_sample/</code> (4-tool sample server).
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary">Track Override Hint (Optional)</label>
                  <div className="flex gap-4">
                    {[
                      { value: "auto", label: "Auto-detect (Recommended)" },
                      { value: "mcp_native", label: "MCP-Native (FastMCP)" },
                      { value: "openapi", label: "OpenAPI / Swagger Spec" },
                    ].map((opt) => (
                      <label key={opt.value} className="flex items-center gap-2 cursor-pointer text-xs text-text-primary font-mono">
                        <input
                          type="radio"
                          name="trackHint"
                          value={opt.value}
                          checked={trackHint === opt.value}
                          onChange={() => setTrackHint(opt.value as any)}
                          className="accent-purple-500"
                        />
                        {opt.label}
                      </label>
                    ))}
                  </div>
                </div>

                {turn1Error && (
                  <div className="p-4 rounded-xl bg-status-red/10 border border-status-red/30 text-status-red text-xs font-mono space-y-2">
                    <div className="font-bold flex items-center gap-1.5">
                      <span>
                        🔴 Inspection Failed{" "}
                        {turn1Error.match(/^(\d{3})\b/)
                          ? `(HTTP ${turn1Error.match(/^(\d{3})\b/)?.[1]})`
                          : ""}
                      </span>
                    </div>
                    <div className="break-words">{turn1Error}</div>
                    <button
                      onClick={startNewSession}
                      className="px-3 py-1 rounded bg-status-red/20 border border-status-red/40 hover:bg-status-red/30 text-white font-bold transition-all"
                    >
                      Try Again / Start New Session
                    </button>
                  </div>
                )}

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={handleStartTurn1}
                    disabled={!canGovern || !sourceUrl.trim() || startMutation.isPending}
                    className="px-6 py-3 rounded-xl bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white font-semibold text-sm shadow-lg shadow-purple-500/20 disabled:opacity-50 transition-all flex items-center gap-2"
                  >
                    {startMutation.isPending ? "Inspecting Repo…" : "Inspect Source Repo →"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* TURN 2: SYNTHESIZE */}
          {session && session.status === "inspected" && session.inspection_report && (
            <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">🛠️</span>
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Turn 2 — Select Tool &amp; Synthesize Manifest</h2>
                    <p className="text-xs text-text-secondary">
                      Select one tool from the inspection report to synthesize into a governed ADOS capability.
                    </p>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded text-xs font-mono bg-cobalt/20 text-cobalt border border-cobalt/30 font-semibold">
                  Track: {session.track?.toUpperCase()}
                </span>
              </div>

              {session.inspection_report.warnings.length > 0 && (
                <div className="p-3 rounded-xl bg-amber/10 border border-amber/30 text-amber text-xs font-mono space-y-1">
                  <div className="font-bold">⚠️ Inspection Warnings:</div>
                  {session.inspection_report.warnings.map((w, idx) => (
                    <div key={idx}>• {w}</div>
                  ))}
                </div>
              )}

              {/* Tools Selection List */}
              <div className="space-y-3">
                <label className="text-xs font-mono text-text-secondary">Discovered Tools ({session.inspection_report.tools.length}) *</label>
                <div className="grid grid-cols-1 gap-3 max-h-80 overflow-y-auto pr-1">
                  {session.inspection_report.tools.map((t: DiscoveredTool) => {
                    const isSelected = selectedToolName === t.name;
                    const isSchemaExpanded = expandedSchemaTool === t.name;

                    return (
                      <div
                        key={t.name}
                        onClick={() => {
                          setSelectedToolName(t.name);
                          setCapabilityId(t.name.replace(/[^a-zA-Z0-9]/g, ""));
                        }}
                        className={`p-4 rounded-2xl border cursor-pointer transition-all ${
                          isSelected
                            ? "bg-purple-900/40 border-purple-400 shadow-lg shadow-purple-500/10"
                            : "bg-glass border-border-subtle hover:border-purple-500/40"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <input
                              type="radio"
                              name="toolSelection"
                              checked={isSelected}
                              onChange={() => {}}
                              className="accent-purple-500"
                            />
                            <div>
                              <div className="text-sm font-semibold font-mono text-text-primary">{t.name}</div>
                              <div className="text-xs text-text-secondary mt-0.5">{t.description || "(No description provided)"}</div>
                            </div>
                          </div>

                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedSchemaTool(isSchemaExpanded ? null : t.name);
                            }}
                            className="px-2.5 py-1 rounded text-[11px] font-mono bg-glass border border-border-subtle hover:border-purple-400 text-text-secondary"
                          >
                            {isSchemaExpanded ? "Hide Schema" : "View Input Schema"}
                          </button>
                        </div>

                        {isSchemaExpanded && (
                          <div className="mt-3 p-3 rounded-xl bg-[#08051a] border border-border-subtle text-[11px] font-mono text-purple-200/90 overflow-x-auto">
                            <pre>{JSON.stringify(t.input_schema, null, 2)}</pre>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Form Metadata */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <div className="space-y-1">
                  <label className="text-xs font-mono text-text-secondary">Target Domain *</label>
                  <select
                    value={domain}
                    onChange={(e) => setDomain(e.target.value)}
                    className="w-full rounded-xl border border-border-subtle bg-glass px-3 py-2.5 text-sm text-text-primary font-mono"
                  >
                    <option value="it">IT Domain</option>
                    <option value="hr">HR Domain</option>
                    <option value="manufacturing">Manufacturing Domain</option>
                    <option value="finance">Finance Domain</option>
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-mono text-text-secondary">Capability ID *</label>
                  <input
                    type="text"
                    value={capabilityId}
                    onChange={(e) => setCapabilityId(e.target.value)}
                    placeholder="e.g. QueryInventoryDb"
                    className="w-full rounded-xl border border-border-subtle bg-glass px-3 py-2.5 text-sm text-text-primary font-mono"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-mono text-text-secondary">Version</label>
                  <input
                    type="text"
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                    placeholder="1.0.0"
                    className="w-full rounded-xl border border-border-subtle bg-glass px-3 py-2.5 text-sm text-text-primary font-mono"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-mono text-text-secondary">Estimated Cost (USD)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={estimatedCostUsd}
                    onChange={(e) => setEstimatedCostUsd(parseFloat(e.target.value) || 0)}
                    placeholder="0.00"
                    className="w-full rounded-xl border border-border-subtle bg-glass px-3 py-2.5 text-sm text-text-primary font-mono"
                  />
                </div>

                {session.track === "openapi" && (
                  <>
                    <div className="space-y-1">
                      <label className="text-xs font-mono text-text-secondary">Test Base URL * (OpenAPI Track)</label>
                      <input
                        type="text"
                        value={testBaseUrl}
                        onChange={(e) => setTestBaseUrl(e.target.value)}
                        placeholder="http://localhost:8000/mock-api"
                        className="w-full rounded-xl border border-border-subtle bg-glass px-3 py-2.5 text-sm text-text-primary font-mono"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-xs font-mono text-text-secondary">Production Base URL (Optional)</label>
                      <input
                        type="text"
                        value={productionBaseUrl}
                        onChange={(e) => setProductionBaseUrl(e.target.value)}
                        placeholder="https://api.enterprise.com/v1"
                        className="w-full rounded-xl border border-border-subtle bg-glass px-3 py-2.5 text-sm text-text-primary font-mono"
                      />
                    </div>
                  </>
                )}
              </div>

              {turn2Error && (
                <div className="p-4 rounded-xl bg-status-red/10 border border-status-red/30 text-status-red text-xs font-mono">
                  🔴 {turn2Error}
                </div>
              )}

              <div className="pt-2 flex justify-end">
                <button
                  onClick={handleSynthesizeTurn2}
                  disabled={!canGovern || !selectedToolName || !domain || !capabilityId || synthesizeMutation.isPending}
                  className="px-6 py-3 rounded-xl bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white font-semibold text-sm shadow-lg shadow-purple-500/20 disabled:opacity-50 transition-all"
                >
                  {synthesizeMutation.isPending ? "Synthesizing Manifest…" : "Synthesize Capability Manifest →"}
                </button>
              </div>
            </div>
          )}

          {/* TURN 3: RISK PROPOSAL */}
          {session && session.status === "synthesized" && session.synthesized_manifest && (
            <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">🛡️</span>
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Turn 3 — Risk Classification &amp; Policy Registration</h2>
                    <p className="text-xs text-text-secondary">
                      Evaluate governance risk profile and instantiate manifest row in CapabilityManifestRegistry.
                    </p>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded text-xs font-mono bg-amber/20 text-amber border border-amber/30 font-semibold">
                  Turn 3 of 5
                </span>
              </div>

              <div className="p-4 rounded-2xl bg-glass border border-border-subtle space-y-3 font-mono text-xs">
                <div className="flex justify-between border-b border-border-subtle/50 pb-2">
                  <span className="text-text-secondary">Capability Key:</span>
                  <span className="text-cobalt font-bold">{session.synthesized_manifest.key}</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-2">
                  <span className="text-text-secondary">Target Domain:</span>
                  <span className="text-purple font-bold">{session.domain}</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-2">
                  <span className="text-text-secondary">Estimated Cost (USD):</span>
                  <span className="text-emerald font-bold">${session.synthesized_manifest.estimated_cost_usd}</span>
                </div>
                <div>
                  <span className="text-text-secondary block mb-1">Description:</span>
                  <span className="text-text-primary">{session.synthesized_manifest.description}</span>
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={handleRiskProposalTurn3}
                  disabled={!canGovern || riskProposalMutation.isPending}
                  className="px-6 py-3 rounded-xl bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white font-semibold text-sm shadow-lg shadow-purple-500/20 disabled:opacity-50 transition-all"
                >
                  {riskProposalMutation.isPending ? "Calculating Risk Tier…" : "Propose Governance Risk Tier →"}
                </button>
              </div>
            </div>
          )}

          {/* TURN 4: SANDBOX TEST */}
          {session && session.status === "risk_reviewed" && (
            <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">🧪</span>
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Turn 4 — Docker / HTTP Sandbox Execution</h2>
                    <p className="text-xs text-text-secondary">
                      Execute real test payload against the capability in network-isolated sandbox environment.
                    </p>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded text-xs font-mono bg-cyan/20 text-cyan border border-cyan/30 font-semibold">
                  Turn 4 of 5
                </span>
              </div>

              {/* Show Audit entry from Turn 3 risk tier */}
              {session.audit_log.length >= 3 && (
                <div className="p-4 rounded-2xl bg-cyan/10 border border-cyan/30 text-xs font-mono text-cyan space-y-1">
                  <div className="font-bold">🛡️ Computed Governance Risk Tier:</div>
                  <div>{session.audit_log[session.audit_log.length - 1]?.detail}</div>
                </div>
              )}

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-mono text-text-secondary">Sample Input Payload (JSON Format)</label>
                  <textarea
                    rows={6}
                    value={sampleInputJson}
                    onChange={(e) => setSampleInputJson(e.target.value)}
                    placeholder='{ "key": "value" }'
                    className="w-full rounded-xl border border-border-subtle bg-[#08051a] p-4 text-xs text-purple-200 font-mono focus:border-purple-400 outline-none resize-none"
                  />
                </div>

                {session.track === "openapi" && (
                  <div className="p-4 rounded-xl bg-amber/10 border border-amber/30 space-y-2">
                    <label className="flex items-center gap-2.5 cursor-pointer text-xs font-mono text-amber">
                      <input
                        type="checkbox"
                        checked={acknowledgeLiveCall}
                        onChange={(e) => setAcknowledgeLiveCall(e.target.checked)}
                        className="accent-amber-500 w-4 h-4"
                      />
                      <span className="font-bold">Acknowledge Live HTTP Request</span>
                    </label>
                    <p className="text-[11px] text-text-secondary font-mono pl-6">
                      The OpenAPI track executes live HTTP calls against the specified test base URL. Check this box to confirm.
                    </p>
                  </div>
                )}

                {/* Turn 4 Error Display (Retriable 422) */}
                {turn4Error && (
                  <div className="p-4 rounded-xl bg-status-red/10 border border-status-red/30 text-status-red text-xs font-mono space-y-2">
                    <div className="font-bold">⚠️ Sandbox Execution Failed (Retriable)</div>
                    <div>{turn4Error}</div>
                    <div className="text-[11px] text-text-secondary">
                      Session remains in RISK_REVIEWED state. Adjust the sample input payload above and retry the test.
                    </div>
                  </div>
                )}

                {/* Display previous Sandbox Result if available */}
                {session.sandbox_result && (
                  <div
                    className={`p-4 rounded-2xl border text-xs font-mono space-y-3 ${
                      session.sandbox_result.passed
                        ? "bg-emerald/10 border-emerald/30 text-emerald"
                        : "bg-status-red/10 border-status-red/30 text-status-red"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="font-bold flex items-center gap-2">
                        <span>{session.sandbox_result.passed ? "🟢 PASSED" : "🔴 FAILED"}</span>
                        <span>({session.sandbox_result.duration_ms} ms)</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => setShowRawOutput(!showRawOutput)}
                        className="px-2.5 py-1 rounded text-[11px] bg-glass border border-border-subtle text-text-secondary hover:text-text-primary"
                      >
                        {showRawOutput ? "Hide Details" : "Show Raw Log Output"}
                      </button>
                    </div>

                    <div>{session.sandbox_result.evidence_summary}</div>

                    {showRawOutput && (
                      <div className="p-3 rounded-xl bg-[#08051a] border border-border-subtle text-purple-200 text-[11px] overflow-x-auto max-h-60">
                        <pre>{session.sandbox_result.raw_output || "(No output recorded)"}</pre>
                      </div>
                    )}
                  </div>
                )}

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={handleSandboxTestTurn4}
                    disabled={!canGovern || (session.track === "openapi" && !acknowledgeLiveCall) || sandboxTestMutation.isPending}
                    className="px-6 py-3 rounded-xl bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white font-semibold text-sm shadow-lg shadow-purple-500/20 disabled:opacity-50 transition-all"
                  >
                    {sandboxTestMutation.isPending ? "Executing Sandbox Test…" : "Run Sandbox Test →"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* TURN 5: ACTIVATE */}
          {session && session.status === "sandbox_tested" && (
            <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">🚀</span>
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Turn 5 — Final Human Activation Gate</h2>
                    <p className="text-xs text-text-secondary">
                      Review sandbox evidence summary and promote capability to live MOA execution registry.
                    </p>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded text-xs font-mono bg-pink/20 text-pink border border-pink/30 font-semibold">
                  Turn 5 of 5
                </span>
              </div>

              <div className="p-4 rounded-2xl bg-glass border border-border-subtle space-y-3 text-xs font-mono">
                <div className="flex justify-between border-b border-border-subtle/50 pb-2">
                  <span className="text-text-secondary">Capability ID:</span>
                  <span className="text-emerald font-bold">{session.capability_id}</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-2">
                  <span className="text-text-secondary">Domain:</span>
                  <span className="text-purple font-bold">{session.domain}</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-2">
                  <span className="text-text-secondary">Selected Tool:</span>
                  <span className="text-cobalt font-bold">{session.selected_tool_name}</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-2">
                  <span className="text-text-secondary">Sandbox Status:</span>
                  <span className="text-emerald font-bold">✓ PASSED ({session.sandbox_result?.duration_ms} ms)</span>
                </div>
                <div>
                  <span className="text-text-secondary block mb-1">Evidence Summary:</span>
                  <span className="text-text-primary">{session.sandbox_result?.evidence_summary}</span>
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={handleActivateTurn5}
                  disabled={!canGovern || activateMutation.isPending}
                  className="px-6 py-3 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold text-sm shadow-lg shadow-emerald-500/20 disabled:opacity-50 transition-all"
                >
                  {activateMutation.isPending ? "Activating Capability…" : "Activate & Promote to MOA →"}
                </button>
              </div>
            </div>
          )}

          {/* COMPLETED ACTIVATED VIEW */}
          {session && session.status === "activated" && (
            <div className="rounded-3xl jarvis-glass-card border border-emerald-500/40 bg-[#0c0824]/90 backdrop-blur-xl p-8 text-center space-y-6 shadow-2xl">
              <div className="inline-flex p-4 rounded-full bg-emerald/20 border border-emerald/40 text-emerald text-3xl">
                🎉
              </div>
              <div className="space-y-2">
                <h2 className="text-xl font-bold text-text-primary">Capability Successfully Activated!</h2>
                <p className="text-xs text-text-secondary max-w-lg mx-auto">
                  <code className="text-emerald font-bold">{session.capability_id}</code> is now live in domain{" "}
                  <code className="text-purple font-bold">{session.domain}</code> and ready to be invoked by the MOA orchestrator.
                </p>
              </div>

              <div className="flex justify-center gap-4 pt-2">
                <Link
                  href="/integrations"
                  className="px-5 py-2.5 rounded-xl bg-emerald/20 border border-emerald/40 text-emerald hover:bg-emerald/30 font-mono text-xs font-bold transition-all"
                >
                  View in Integrations Registry →
                </Link>
                <button
                  onClick={startNewSession}
                  className="px-5 py-2.5 rounded-xl bg-glass border border-border-subtle text-text-secondary hover:text-text-primary font-mono text-xs transition-all"
                >
                  + Onboard Another Capability
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* SESSION HISTORY & AUDIT LOGS TAB */}
      {activeTab === "history" && (
        <div className="space-y-6">
          <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 sm:p-8 space-y-6 shadow-2xl">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-text-primary">Onboarding Sessions Log</h2>
                <p className="text-xs text-text-secondary mt-0.5">
                  Complete history of capability onboarding requests and governance audit logs.
                </p>
              </div>
              <span className="text-xs font-mono text-text-secondary">
                Total Sessions: {sessionsQuery.data?.length ?? 0}
              </span>
            </div>

            {sessionsQuery.isLoading && (
              <p className="text-xs font-mono text-text-secondary">Loading onboarding sessions history...</p>
            )}

            {sessionsQuery.data && sessionsQuery.data.length === 0 && (
              <p className="text-xs font-mono text-text-secondary">No onboarding sessions recorded yet.</p>
            )}

            <div className="grid grid-cols-1 gap-4">
              {sessionsQuery.data?.map((s) => (
                <div
                  key={s.id}
                  className="p-5 rounded-2xl jarvis-glass-card border border-purple-500/20 hover:border-purple-500/40 transition-all space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs text-purple-300 font-bold">{s.id.slice(0, 8)}</span>
                      <span className={`px-2.5 py-0.5 rounded text-[10px] font-mono border font-bold ${STATUS_BADGES[s.status]}`}>
                        {s.status.toUpperCase()}
                      </span>
                      {s.track && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-glass border border-border-subtle text-text-secondary">
                          {s.track}
                        </span>
                      )}
                    </div>
                    <span className="text-[11px] font-mono text-text-secondary">
                      {new Date(s.created_at).toLocaleString()}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs font-mono">
                    <div>
                      <span className="text-text-secondary block text-[10px]">Source URL:</span>
                      <span className="text-text-primary truncate block">{s.source_url}</span>
                    </div>
                    <div>
                      <span className="text-text-secondary block text-[10px]">Capability ID:</span>
                      <span className="text-cobalt font-semibold">{s.capability_id || "—"}</span>
                    </div>
                    <div>
                      <span className="text-text-secondary block text-[10px]">Created By:</span>
                      <span className="text-text-primary">{s.created_by}</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-2 border-t border-border-subtle/50">
                    <button
                      onClick={() => setSelectedAuditSession(s)}
                      className="text-xs font-mono text-purple-300 hover:text-white flex items-center gap-1"
                    >
                      📜 View Audit Log ({s.audit_log.length} entries) →
                    </button>

                    {s.status !== "activated" && s.status !== "failed" && s.status !== "aborted" && (
                      <button
                        onClick={() => {
                          setCurrentSessionId(s.id);
                          setActiveTab("wizard");
                        }}
                        className="px-3 py-1 rounded text-xs font-mono bg-purple/20 text-purple border border-purple/30 hover:bg-purple/30 transition-all font-semibold"
                      >
                        Resume Wizard →
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* AUDIT LOG MODAL / DRAWER */}
      {selectedAuditSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-2xl rounded-3xl jarvis-glass-card border border-purple-500/40 bg-[#0c0824] p-6 space-y-6 shadow-2xl max-h-[85vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-border-subtle pb-4">
              <div>
                <h3 className="text-base font-bold text-text-primary">Session Audit Log &amp; Governance Trail</h3>
                <span className="text-xs font-mono text-purple-300">{selectedAuditSession.id}</span>
              </div>
              <button
                onClick={() => setSelectedAuditSession(null)}
                className="p-2 text-text-secondary hover:text-white font-bold"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div className="text-xs font-mono text-text-secondary">Audit Trail Entries ({selectedAuditSession.audit_log.length}):</div>

              <div className="space-y-2 font-mono text-xs">
                {selectedAuditSession.audit_log.map((log: AuditLogEntry, idx: number) => (
                  <div key={idx} className="p-3 rounded-xl bg-glass border border-border-subtle space-y-1">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-purple font-bold">Turn {log.turn}</span>
                      <span className="text-text-secondary">{new Date(log.at).toLocaleTimeString()}</span>
                    </div>
                    <div className="text-text-primary">{log.detail}</div>
                    <div className="text-[10px] text-text-secondary">Actor: {log.actor}</div>
                  </div>
                ))}
              </div>

              {selectedAuditSession.sandbox_result && (
                <div className="p-4 rounded-xl bg-glass border border-border-subtle space-y-2 text-xs font-mono">
                  <div className="font-bold text-text-primary">Sandbox Execution Summary:</div>
                  <div className={selectedAuditSession.sandbox_result.passed ? "text-emerald" : "text-status-red"}>
                    {selectedAuditSession.sandbox_result.evidence_summary}
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setSelectedAuditSession(null)}
                className="px-4 py-2 rounded-xl bg-glass border border-border-subtle text-xs font-mono text-text-secondary hover:text-text-primary"
              >
                Close Audit View
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
