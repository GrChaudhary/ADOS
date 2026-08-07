"use client";

import { useState, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, MOATaskResponse, ITSMAskResponse, ExecutiveCopilotAskResponse } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

export function LangGraphAgentWorkspace() {
  const hasToken = useHasToken();
  const [activeTab, setActiveTab] = useState<"moa" | "itsm" | "executive">("moa");

  // MOA Form state
  const [domain, setDomain] = useState<"hr" | "it" | "finance" | "manufacturing" | "cross-domain">("hr");
  const [employeeName, setEmployeeName] = useState("Marcus Vance");
  const [instruction, setInstruction] = useState("Offboard employee and revoke system accesses");
  const [moaResult, setMoaResult] = useState<MOATaskResponse | null>(null);

  // Quick Preset Handlers
  const handleDomainChange = (newDomain: "hr" | "it" | "finance" | "manufacturing" | "cross-domain") => {
    setDomain(newDomain);
    if (newDomain === "hr") {
      setEmployeeName("Marcus Vance");
      setInstruction("Offboard employee and revoke building and IT access");
    } else if (newDomain === "it") {
      setEmployeeName("DevOps Admin");
      setInstruction("Revoke AWS admin role and deprovision cloud infrastructure account");
    } else if (newDomain === "finance") {
      setEmployeeName("Acme Vendor");
      setInstruction("Flag invoice discrepancy and issue vendor payment hold");
    } else if (newDomain === "manufacturing") {
      setEmployeeName("Production Line 4");
      setInstruction("Update MES line parameters and schedule preventive maintenance");
    } else {
      setEmployeeName("Marcus Vance");
      setInstruction("Execute complete offboarding: revoke building access, revoke AWS cloud role, and hold final paycheck");
    }
  };

  // ITSM Form state
  const [itsmPrompt, setItsmPrompt] = useState("Create a critical incident for database latency on server db-cluster-04");
  const [itsmResult, setItsmResult] = useState<ITSMAskResponse | null>(null);

  // Executive Copilot state
  const [execPrompt, setExecPrompt] = useState("What is our average MTTR and total protected revenue this quarter?");
  const [execResult, setExecResult] = useState<ExecutiveCopilotAskResponse | null>(null);

  // MOA Approval Editing state
  const [editedArgsText, setEditedArgsText] = useState<string>("");
  const [approveError, setApproveError] = useState<string | null>(null);

  useEffect(() => {
    if (moaResult?.status === "pending_approval" && moaResult.proposedAction?.arguments) {
      setEditedArgsText(JSON.stringify(moaResult.proposedAction.arguments, null, 2));
      setApproveError(null);
    } else {
      setEditedArgsText("");
      setApproveError(null);
    }
  }, [moaResult]);

  // Mutations
  const moaTaskMutation = useMutation({
    mutationFn: api.createMOATask,
    onSuccess: (data) => setMoaResult(data),
  });

  const moaApproveMutation = useMutation({
    mutationFn: api.approveMOATask,
    onSuccess: (data) => {
      setApproveError(null);
      setMoaResult(data);
    },
    onError: (err: any) => {
      const msg = err?.message || "Approval failed.";
      const cleanMsg = msg.replace(/^\d+\s+\/api\/backend[^\:]*:\s*/, "");
      setApproveError(cleanMsg);
    },
  });

  const moaRejectMutation = useMutation({
    mutationFn: api.rejectMOATask,
    onSuccess: (data) => setMoaResult(data),
  });

  const itsmAskMutation = useMutation({
    mutationFn: api.askITSMAgent,
    onSuccess: (data) => setItsmResult(data),
  });

  const itsmApproveMutation = useMutation({
    mutationFn: api.approveITSMAgentAction,
    onSuccess: (data) => setItsmResult(data),
  });

  const itsmRejectMutation = useMutation({
    mutationFn: api.rejectITSMAgentAction,
    onSuccess: (data) => setItsmResult(data),
  });

  const execCopilotMutation = useMutation({
    mutationFn: api.askExecutiveCopilotLangGraph,
    onSuccess: (data) => setExecResult(data),
  });

  return (
    <div className="space-y-6">
      {/* Tab Switcher */}
      <div className="flex flex-wrap gap-3 p-2 rounded-2xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl">
        <button
          onClick={() => setActiveTab("moa")}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-xs transition-all duration-200 ${
            activeTab === "moa"
              ? "bg-purple-600/30 text-purple-200 border border-purple-400/50 shadow-lg shadow-purple-500/20"
              : "text-text-secondary hover:text-text-primary hover:bg-white/5"
          }`}
        >
          <span>🧠</span>
          <span>MOA Engine (HR Domain)</span>
          <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-purple/20 text-purple border border-purple/30">
            ReAct Planner
          </span>
        </button>

        <button
          onClick={() => setActiveTab("itsm")}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-xs transition-all duration-200 ${
            activeTab === "itsm"
              ? "bg-cyan-600/30 text-cyan-200 border border-cyan-400/50 shadow-lg shadow-cyan-500/20"
              : "text-text-secondary hover:text-text-primary hover:bg-white/5"
          }`}
        >
          <span>🎫</span>
          <span>ITSM Agent</span>
          <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-cyan/20 text-cyan border border-cyan/30">
            LangGraph
          </span>
        </button>

        <button
          onClick={() => setActiveTab("executive")}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-xs transition-all duration-200 ${
            activeTab === "executive"
              ? "bg-emerald-600/30 text-emerald-200 border border-emerald-400/50 shadow-lg shadow-emerald-500/20"
              : "text-text-secondary hover:text-text-primary hover:bg-white/5"
          }`}
        >
          <span>📊</span>
          <span>Executive Copilot</span>
          <span className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald/20 text-emerald border border-emerald/30">
            Q&amp;A
          </span>
        </button>
      </div>

      {!hasToken && (
        <div className="p-4 rounded-xl border border-status-red/30 bg-status-red/10 text-status-red text-xs font-mono">
          ⚠️ Authentication token required. Please log in or enter service token.
        </div>
      )}

      {/* TIER 1: MOA ENGINE */}
      {activeTab === "moa" && (
        <div className="rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 space-y-6 shadow-2xl">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-purple-500/20 pb-4">
            <div>
              <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
                <span>🧠</span> Main Orchestrating Agent (MOA) — Multi-Domain Pod Workspace
              </h2>
              <p className="text-xs text-text-secondary mt-1">
                Dynamic ReAct planner evaluating actions step-by-step with action-level governance tiering across HR, IT, and Finance domains.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <label className="text-xs font-mono text-text-secondary">Domain Pod:</label>
              <select
                value={domain}
                onChange={(e) => handleDomainChange(e.target.value as any)}
                className="rounded-xl border border-purple-500/40 bg-[#120b38] px-3 py-1.5 text-xs text-purple-200 font-mono outline-none focus:border-purple-400"
              >
                <option value="hr">HR Domain Pod</option>
                <option value="it">IT Domain Pod</option>
                <option value="finance">Finance Domain Pod</option>
                <option value="manufacturing">Manufacturing Pod</option>
                <option value="cross-domain">Cross-Domain Multi-Pod</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs font-mono text-text-secondary">Subject / Employee / Entity</label>
              <input
                type="text"
                value={employeeName}
                onChange={(e) => setEmployeeName(e.target.value)}
                placeholder="e.g. Marcus Vance"
                className="w-full rounded-xl border border-border-subtle bg-glass px-4 py-2.5 text-sm text-text-primary focus:border-purple-500 outline-none"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-mono text-text-secondary">Instruction / Dynamic Intent</label>
              <input
                type="text"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="e.g. Offboard employee and revoke accesses"
                className="w-full rounded-xl border border-border-subtle bg-glass px-4 py-2.5 text-sm text-text-primary focus:border-purple-500 outline-none"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => moaTaskMutation.mutate({ domain, employee_name: employeeName, instruction })}
              disabled={!hasToken || moaTaskMutation.isPending || !employeeName.trim() || !instruction.trim()}
              className="px-6 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-medium text-xs shadow-lg shadow-purple-500/25 disabled:opacity-50 transition-all"
            >
              {moaTaskMutation.isPending ? "Executing Dynamic Planner..." : "Execute MOA Intent"}
            </button>
          </div>

          {/* MOA Response Display */}
          {moaResult && (
            <div className="space-y-4 pt-4 border-t border-purple-500/20">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-text-secondary">MOA Execution Status:</span>
                <span
                  className={`px-2.5 py-0.5 rounded text-xs font-mono font-semibold border ${
                    moaResult.status === "pending_approval"
                      ? "bg-amber/20 text-amber border-amber/40"
                      : moaResult.status === "ok"
                      ? "bg-emerald/20 text-emerald border-emerald/40"
                      : "bg-status-red/20 text-status-red border-status-red/40"
                  }`}
                >
                  {moaResult.status.toUpperCase()}
                </span>
              </div>

              {moaResult.answer && (
                <div className="p-4 rounded-2xl bg-glass border border-purple-500/30 space-y-2">
                  <div className="text-xs font-mono text-purple font-semibold">MOA Summary Answer:</div>
                  <div className="text-sm text-text-primary">{moaResult.answer}</div>
                </div>
              )}

              {moaResult.toolsCalled && moaResult.toolsCalled.length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-xs font-mono text-text-secondary">Actions Executed in Loop:</span>
                  <div className="flex flex-wrap gap-2">
                    {moaResult.toolsCalled.map((tool, idx) => (
                      <span key={idx} className="px-2.5 py-1 rounded text-xs font-mono bg-purple/10 text-purple border border-purple/30">
                        ⚡ {tool}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* HELD ACTION APPROVAL CARD */}
              {moaResult.status === "pending_approval" && (
                <div className="p-5 rounded-2xl jarvis-glass-card border border-amber-500/50 bg-amber-500/10 space-y-4 shadow-xl">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-amber font-semibold text-sm">
                      <span>⚠️</span> Action Held for Governance Approval
                    </div>
                    {moaResult.proposedAction && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-amber/20 text-amber border border-amber/40 font-bold">
                        TIER {moaResult.proposedAction.policy_tier ?? 1}
                      </span>
                    )}
                  </div>

                  {moaResult.proposedAction ? (
                    <div className="space-y-3 font-mono text-xs text-text-primary">
                      <div>Action: <span className="font-bold text-amber">{moaResult.proposedAction.action_key}</span></div>
                      <div>Summary: {moaResult.proposedAction.summary}</div>
                      <div>Estimated Exposure: ${moaResult.proposedAction.estimated_cost_usd?.toLocaleString("en-US")} USD</div>

                      {/* Render argument editor if input_schema or arguments are present */}
                      {Boolean(
                        moaResult.proposedAction.input_schema?.properties &&
                          Object.keys(moaResult.proposedAction.input_schema.properties).length > 0
                      ) && (
                          <div className="pt-2 border-t border-amber-500/20 space-y-2">
                            <div className="flex items-center justify-between">
                              <span className="text-[11px] font-bold text-amber">Proposed Action Arguments (Editable):</span>
                              {Array.isArray(moaResult.proposedAction.input_schema?.required) &&
                                moaResult.proposedAction.input_schema!.required.length > 0 && (
                                  <span className="text-[10px] text-text-secondary">
                                    Required: {(moaResult.proposedAction.input_schema!.required as string[]).join(", ")}
                                  </span>
                                )}
                            </div>
                            <textarea
                              rows={4}
                              value={editedArgsText}
                              onChange={(e) => {
                                setEditedArgsText(e.target.value);
                                setApproveError(null);
                              }}
                              className="w-full rounded-xl border border-amber-500/30 bg-[#08051a] p-3 text-xs text-amber-200 font-mono focus:border-amber-400 outline-none resize-none"
                              placeholder='{ "param": "value" }'
                            />
                          </div>
                        )}
                    </div>
                  ) : (
                    <div className="text-xs font-mono text-text-secondary">
                      Task <code className="text-amber">{moaResult.taskId}</code> is paused waiting for operator sign-off on the next planned step.
                    </div>
                  )}

                  {approveError && (
                    <div className="p-3 rounded-xl bg-status-red/10 border border-status-red/30 text-status-red text-xs font-mono">
                      🔴 {approveError}
                    </div>
                  )}

                  <div className="flex items-center gap-3 pt-2">
                    <button
                      onClick={() => {
                        if (!moaResult.taskId) return;
                        if (
                          moaResult.proposedAction?.input_schema?.properties &&
                          Object.keys(moaResult.proposedAction.input_schema.properties).length > 0
                        ) {
                          let parsed: Record<string, unknown> = {};
                          try {
                            if (editedArgsText.trim()) {
                              parsed = JSON.parse(editedArgsText);
                            }
                          } catch {
                            setApproveError("Invalid JSON in edited arguments. Please verify format.");
                            return;
                          }
                          moaApproveMutation.mutate({ taskId: moaResult.taskId, editedArguments: parsed });
                        } else {
                          moaApproveMutation.mutate(moaResult.taskId);
                        }
                      }}
                      disabled={moaApproveMutation.isPending}
                      className="px-4 py-2 rounded-xl bg-emerald hover:bg-emerald/90 text-white text-xs font-semibold shadow-md disabled:opacity-50"
                    >
                      {moaApproveMutation.isPending ? "Approving..." : "✅ Approve & Resume Execution"}
                    </button>

                    <button
                      onClick={() => moaResult.taskId && moaRejectMutation.mutate(moaResult.taskId)}
                      disabled={moaRejectMutation.isPending}
                      className="px-4 py-2 rounded-xl bg-status-red hover:bg-status-red/90 text-white text-xs font-semibold shadow-md disabled:opacity-50"
                    >
                      {moaRejectMutation.isPending ? "Rejecting..." : "❌ Reject Action"}
                    </button>
                  </div>
                </div>
              )}

              {/* ReAct Trajectory Timeline */}
              {moaResult.trajectoryLog && moaResult.trajectoryLog.length > 0 && (
                <div className="space-y-3 pt-4 border-t border-purple-500/20">
                  <h3 className="text-xs font-mono font-semibold text-purple-300 uppercase tracking-wider flex items-center gap-2">
                    <span>⏱️</span> ReAct Reasoning Trajectory Timeline ({moaResult.trajectoryLog.length} Steps)
                  </h3>
                  <div className="space-y-2 font-mono text-xs">
                    {moaResult.trajectoryLog.map((step, idx) => (
                      <div key={idx} className="p-3 rounded-xl bg-glass border border-purple-500/20 space-y-1">
                        <div className="flex items-center justify-between text-text-secondary">
                          <span className="font-bold text-purple-400">Step #{step.step}</span>
                          <span className="text-[10px] text-text-secondary">{new Date(step.timestamp).toLocaleTimeString()}</span>
                        </div>
                        <div className="text-text-primary text-[11px] leading-relaxed whitespace-pre-wrap">{step.thought}</div>
                        {step.action && (
                          <div className="flex items-center gap-2 pt-1">
                            <span className="text-[10px] px-2 py-0.5 rounded bg-purple/20 text-purple border border-purple/30 font-bold">
                              ACTION: {step.action}
                            </span>
                            {step.policy_tier !== undefined && (
                              <span className="text-[10px] px-2 py-0.5 rounded bg-amber/20 text-amber border border-amber/30 font-bold">
                                TIER {step.policy_tier}
                              </span>
                            )}
                            <span className="text-[10px] text-emerald font-semibold uppercase">{step.status}</span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* TIER 2: ITSM AGENT */}
      {activeTab === "itsm" && (
        <div className="rounded-3xl jarvis-glass-card border border-cyan-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 space-y-6 shadow-2xl">
          <div className="flex items-center justify-between border-b border-cyan-500/20 pb-4">
            <div>
              <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
                <span>🎫</span> ITSM Technical Agent Workspace
              </h2>
              <p className="text-xs text-text-secondary mt-1">
                LangGraph ITSM Agent executing ServiceNow ticket creation with mandatory human sign-off gates.
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-mono text-text-secondary">Request / Ticket Instructions</label>
            <textarea
              value={itsmPrompt}
              onChange={(e) => setItsmPrompt(e.target.value)}
              rows={3}
              className="w-full rounded-xl border border-border-subtle bg-glass px-4 py-3 text-sm text-text-primary focus:border-cyan-500 outline-none resize-none"
            />
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => itsmAskMutation.mutate(itsmPrompt)}
              disabled={!hasToken || itsmAskMutation.isPending || !itsmPrompt.trim()}
              className="px-6 py-2.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-medium text-xs shadow-lg shadow-cyan-500/25 disabled:opacity-50 transition-all"
            >
              {itsmAskMutation.isPending ? "Running Agent..." : "Submit ITSM Prompt"}
            </button>
          </div>

          {itsmResult && (
            <div className="space-y-4 pt-4 border-t border-cyan-500/20">
              <div className="p-4 rounded-2xl bg-glass border border-cyan-500/30 space-y-2">
                <div className="text-xs font-mono text-cyan font-semibold">Agent Response:</div>
                <div className="text-sm text-text-primary">{itsmResult.answer || "Processing request..."}</div>
              </div>

              {itsmResult.status === "pending_approval" && itsmResult.requestId && (
                <div className="p-5 rounded-2xl jarvis-glass-card border border-amber-500/50 bg-amber-500/10 space-y-4 shadow-xl">
                  <div className="flex items-center gap-2 text-amber font-semibold text-sm">
                    <span>⚠️</span> Ticket Creation Paused for Approval
                  </div>
                  <p className="text-xs text-text-secondary">
                    Request <code className="text-amber">{itsmResult.requestId}</code> is waiting for human confirmation before writing to ServiceNow.
                  </p>

                  {itsmResult.proposedIncident && (
                    <div className="p-3 rounded-lg bg-glass border border-amber-500/30 font-mono text-xs text-text-primary space-y-1">
                      <div className="font-bold text-amber">{itsmResult.proposedIncident.short_description}</div>
                      <div className="text-text-secondary">{itsmResult.proposedIncident.description}</div>
                    </div>
                  )}

                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => itsmResult.requestId && itsmApproveMutation.mutate(itsmResult.requestId)}
                      disabled={itsmApproveMutation.isPending}
                      className="px-4 py-2 rounded-xl bg-emerald hover:bg-emerald/90 text-white text-xs font-semibold disabled:opacity-50"
                    >
                      {itsmApproveMutation.isPending ? "Approving..." : "Approve Ticket Creation"}
                    </button>
                    <button
                      onClick={() => itsmResult.requestId && itsmRejectMutation.mutate(itsmResult.requestId)}
                      disabled={itsmRejectMutation.isPending}
                      className="px-4 py-2 rounded-xl bg-status-red hover:bg-status-red/90 text-white text-xs font-semibold disabled:opacity-50"
                    >
                      {itsmRejectMutation.isPending ? "Rejecting..." : "Reject Ticket"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}


      {/* TIER 3: EXECUTIVE COPILOT */}
      {activeTab === "executive" && (
        <div className="rounded-3xl jarvis-glass-card border border-emerald-500/30 bg-[#0c0824]/90 backdrop-blur-xl p-6 space-y-6 shadow-2xl">
          <div className="flex items-center justify-between border-b border-emerald-500/20 pb-4">
            <div>
              <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
                <span>📊</span> Executive Intelligence Q&amp;A Copilot
              </h2>
              <p className="text-xs text-text-secondary mt-1">
                LangGraph copilot analyzing system KPIs, financial risk, and incident analytics.
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-mono text-text-secondary">Executive Question</label>
            <input
              type="text"
              value={execPrompt}
              onChange={(e) => setExecPrompt(e.target.value)}
              className="w-full rounded-xl border border-border-subtle bg-glass px-4 py-3 text-sm text-text-primary focus:border-emerald-500 outline-none"
            />
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => execCopilotMutation.mutate(execPrompt)}
              disabled={!hasToken || execCopilotMutation.isPending || !execPrompt.trim()}
              className="px-6 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs shadow-lg shadow-emerald-500/25 disabled:opacity-50 transition-all"
            >
              {execCopilotMutation.isPending ? "Querying..." : "Ask Copilot"}
            </button>
          </div>

          {execResult && (
            <div className="space-y-4 pt-4 border-t border-emerald-500/20">
              <div className="p-4 rounded-2xl bg-glass border border-emerald-500/30 space-y-2">
                <div className="text-xs font-mono text-emerald font-semibold">Executive Insights Answer:</div>
                <div className="text-sm text-text-primary">{execResult.answer}</div>
              </div>
              {execResult.toolsCalled && execResult.toolsCalled.length > 0 && (
                <div className="flex flex-wrap gap-2 text-xs font-mono text-text-secondary">
                  <span>Data Sources Checked:</span>
                  {execResult.toolsCalled.map((t, idx) => (
                    <span key={idx} className="px-2 py-0.5 rounded bg-emerald/10 text-emerald border border-emerald/30">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
