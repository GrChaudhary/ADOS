"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import styles from "./studio.module.css";
import { api, CausalChainEntry, CopilotAskResult, DecisionMemorySearchResult } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";
import GovernancePolicyPage from "@/app/governance/page";
import PolicyStudioPage from "@/app/policy-studio/page";
import AgentNetworkPage from "@/app/agents/network/page";
import IntegrationsPage from "@/app/integrations/page";

/* ============================================================
   Novus Studio Applied-AI Dashboard Data & Types
   ============================================================ */

export type StudioTab = "reasoning" | "autonomy" | "agents" | "hub" | "copilot";

const GOVERNANCE_RULES = [
  { tier: "Tier 0", name: "Autonomous Execution", costLimit: "< $25,000", confGate: "> 90%", action: "Executes automatically via ADOS Autonomous Orchestrator", status: "ACTIVE" },
  { tier: "Tier 1", name: "Plant Manager Approval", costLimit: "$500 - $5,000", confGate: "60% - 85%", action: "Routes to Plant Manager digital sign-off queue", status: "REQUIRED FOR INC-94821" },
  { tier: "Tier 2", name: "Executive Safety Lockout", costLimit: "> $5,000", confGate: "< 60%", action: "Requires multi-executive approval + emergency line pause", status: "STANDBY" },
];

/* ============================================================
   Helper: turn a real CausalChainEntry's evidence path string
   ("CNC Telemetry -> Spindle Vibration -> Bore Measurement Deviation")
   into DAG nodes for the Causal Isolation Engine view. The evidence path
   is the data provenance trail; the final node is the condition the
   Bayesian causal graph actually concluded, carrying its real weight.
   ============================================================ */
interface CausalDagNode {
  kind: "source" | "evidence" | "cause";
  label: string;
  weight?: number;
}

function buildCausalDagNodes(entry: CausalChainEntry): CausalDagNode[] {
  const pathSegments = (entry.evidencePath[0] ?? "").split(" -> ").map((s) => s.trim()).filter(Boolean);
  const evidenceNodes: CausalDagNode[] = pathSegments.map((label, i) => ({
    kind: i === 0 ? "source" : "evidence",
    label,
  }));
  return [...evidenceNodes, { kind: "cause", label: entry.description, weight: entry.weight }];
}

/* ============================================================
   Helper: turn a /copilot/ask response (knowledge/policy_docs_qa.py) into
   a chat bubble string. Mirrors that endpoint's honest status convention -
   never presents an extractive/no-match/error result as if it were a live
   LLM answer.
   ============================================================ */
function formatCopilotAnswer(result: CopilotAskResult): string {
  const sourceList =
    result.sources.length > 0
      ? ` (source: ${result.sources.map((s) => `${s.doc} — ${s.heading}`).join("; ")})`
      : "";
  if (result.status === "live_llm_generated" && result.answer) {
    return `${result.answer}${sourceList}`;
  }
  if (result.status === "extractive_fallback" && result.answer) {
    return `No live LLM provider is configured — here is the matching policy text directly:\n\n${result.answer}${sourceList}`;
  }
  if (result.status === "no_match") {
    return result.answer ?? "I couldn't find anything in the governance policy documents about that.";
  }
  return `Policy Copilot is unavailable right now (${result.error ?? result.status}).`;
}

/* ============================================================
   Component: Custom Cursor
   ============================================================ */
function CustomCursor() {
  const dotRef = useRef<HTMLDivElement | null>(null);
  const ringRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let raw = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    const ring = { ...raw };
    let frame = 0;

    const onMove = (e: MouseEvent) => {
      raw = { x: e.clientX, y: e.clientY };
      if (dotRef.current) {
        dotRef.current.style.transform = `translate(${raw.x}px, ${raw.y}px) translate(-50%, -50%)`;
      }
    };

    const tick = () => {
      ring.x += (raw.x - ring.x) * 0.18;
      ring.y += (raw.y - ring.y) * 0.18;
      if (ringRef.current) {
        ringRef.current.style.transform = `translate(${ring.x}px, ${ring.y}px) translate(-50%, -50%)`;
      }
      frame = requestAnimationFrame(tick);
    };

    window.addEventListener("mousemove", onMove);
    frame = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <>
      <div ref={dotRef} className={styles.cursorDot} aria-hidden="true" />
      <div ref={ringRef} className={styles.cursorRing} aria-hidden="true" />
    </>
  );
}

/* ============================================================
   Main Studio Dashboard Component
   ============================================================ */
export default function NovusStudioDashboard() {
  const hasToken = useHasToken();
  const [activeTab, setActiveTab] = useState<StudioTab>("reasoning");

  // Real Decision Memory incident records (same backend query /decisions
  // uses) — drives the Reasoning tab's incident picker + causal DAG
  // instead of the hardcoded "Incident #391" mock.
  const reasoningMemoryQuery = useQuery<DecisionMemorySearchResult>({
    queryKey: ["studio-reasoning-memory"],
    queryFn: () => api.searchDecisionMemory({ limit: 20 }),
    enabled: hasToken,
  });
  const reasoningIncidents = useMemo(() => reasoningMemoryQuery.data?.records ?? [], [reasoningMemoryQuery.data]);
  const [selectedReasoningId, setSelectedReasoningId] = useState<string | null>(null);
  useEffect(() => {
    if (!selectedReasoningId && reasoningIncidents.length > 0) {
      // One-time default selection once real Decision Memory records load -
      // syncing local UI state from an external data source, same pattern
      // as policy-studio/page.tsx's localStorage hydration.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedReasoningId(reasoningIncidents[0].incidentId);
    }
  }, [reasoningIncidents, selectedReasoningId]);
  const selectedIncident = reasoningIncidents.find((r) => r.incidentId === selectedReasoningId) ?? null;

  // On-demand LLM causal synthesis for the selected incident — fetched
  // once per selection, not polled (the local LLM call can take up to a
  // minute), and never auto-runs without a real incident to reason about.
  const synthesisQuery = useQuery({
    queryKey: ["studio-causal-synthesis", selectedReasoningId],
    queryFn: () => api.getCausalSynthesis(selectedReasoningId as string),
    enabled: hasToken && !!selectedReasoningId,
    staleTime: Infinity,
    retry: false,
  });


  const [chatMessages, setChatMessages] = useState<Array<{ id: number; sender: "user" | "ai"; text: string; pending?: boolean }>>([
    { id: 0, sender: "ai", text: "Hello Director. I am the ADOS Executive Copilot. CNC Spindle #04 on Line 2 registered a +0.42mm bore tolerance breach. Causal Isolation identified Spindle Bearing Thermal Expansion (87% confidence). How can I assist your operational overview?" }
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const chatIdRef = useRef(1);
  const [simCost, setSimCost] = useState(1250);
  const [simConf, setSimConf] = useState(87);

  // Copilot Message Submit — Line 2/spindle and cost/revenue stay scripted
  // (they narrate the specific opening incident, not a governance policy);
  // everything else is answered live from documentation/08-12 via
  // /copilot/ask (knowledge/policy_docs_qa.py), replacing the old one-line
  // generic fallback.
  const handleChatSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const userText = chatInput.trim();
    if (!userText || chatBusy) return;

    setChatMessages((prev) => [...prev, { id: chatIdRef.current++, sender: "user", text: userText }]);
    setChatInput("");

    const lower = userText.toLowerCase();
    if (lower.includes("line 2") || lower.includes("spindle")) {
      setTimeout(() => {
        setChatMessages((prev) => [
          ...prev,
          { id: chatIdRef.current++, sender: "ai", text: "Line 2 CNC Spindle #04 bore breach is currently isolated. Option B (Cartridge replacement) was executed via ServiceNow CHG0048201. MTTR is estimated at 39 minutes (-84% vs manual baseline)." },
        ]);
      }, 600);
      return;
    }
    if (lower.includes("cost") || lower.includes("revenue")) {
      setTimeout(() => {
        setChatMessages((prev) => [
          ...prev,
          { id: chatIdRef.current++, sender: "ai", text: "The current resolution action protects $142,500 in shift revenue at a total component cost of $1,250." },
        ]);
      }, 600);
      return;
    }

    const pendingId = chatIdRef.current++;
    setChatMessages((prev) => [...prev, { id: pendingId, sender: "ai", text: "Consulting governance policy documents…", pending: true }]);
    setChatBusy(true);
    try {
      const text = hasToken
        ? formatCopilotAnswer(await api.askCopilot(userText))
        : "Log in to consult the governance policy documents.";
      setChatMessages((prev) => prev.map((m) => (m.id === pendingId ? { ...m, text, pending: false } : m)));
    } catch {
      setChatMessages((prev) =>
        prev.map((m) => (m.id === pendingId ? { ...m, text: "Policy Copilot request failed — check backend connectivity.", pending: false } : m))
      );
    } finally {
      setChatBusy(false);
    }
  };

  // Real causal DAG + alternate ranked causes for the selected incident
  const dagNodes = selectedIncident && selectedIncident.causalChain.length > 0
    ? buildCausalDagNodes(selectedIncident.causalChain[0])
    : [];
  const alternateCauses = selectedIncident ? selectedIncident.causalChain.slice(1) : [];

  // Policy Tier Calculator
  const calculatedTier = useMemo(() => {
    if (simCost < 500 && simConf >= 85) return { tier: "Tier 0", label: "Fully Autonomous Execution", color: "#00f0ff" };
    if (simCost <= 5000 && simConf >= 60) return { tier: "Tier 1", label: "Plant Manager Approval Queue", color: "#d7ff3e" };
    return { tier: "Tier 2", label: "Executive Safety Lockout", color: "#ff4b1f" };
  }, [simCost, simConf]);

  return (
    <div className={styles.dashboardRoot}>
      <CustomCursor />

      {/* Single-Row Inline Top Header (Item 2 requirement) */}
      <header className={styles.dashHeaderInline}>
        <div className={styles.headerLeftBrand}>
          <a href="#top" className={styles.wordmark}>
            NOVUS<span>/</span>STUDIO
          </a>
          <span className={styles.liveBadge}>
            <span className={styles.pulseDot} /> APPLIED AI DASHBOARD — PLANT 04
          </span>
        </div>

        {/* Multi-View Tab Bar Inline */}
        <nav className={styles.tabBar}>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "reasoning" ? styles.tabActive : ""}`}
            onClick={() => setActiveTab("reasoning")}
          >
            🧠 01 / REASONING
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "autonomy" ? styles.tabActive : ""}`}
            onClick={() => setActiveTab("autonomy")}
          >
            🛡️ 02 / AUTONOMY
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "agents" ? styles.tabActive : ""}`}
            onClick={() => setActiveTab("agents")}
          >
            🤖 03 / AGENTS
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "hub" ? styles.tabActive : ""}`}
            onClick={() => setActiveTab("hub")}
          >
            🔌 04 / HUB
          </button>
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "copilot" ? styles.tabActive : ""}`}
            onClick={() => setActiveTab("copilot")}
          >
            💬 05 / COPILOT
          </button>
        </nav>
      </header>

      {/* Dashboard Main Content Body */}
      <main className={styles.dashMain}>
        {/* TAB 1: REASONING (CAUSAL ISOLATION ENGINE) */}
        {activeTab === "reasoning" && (
          <div className={styles.tabView}>
            <div className={styles.viewHeader}>
              <h2>🧠 CAUSAL ISOLATION ENGINE</h2>
              <p>Bayesian Causal Graph + Local LLM Root Cause Reasoning — live from Decision Memory</p>
            </div>

            {!hasToken && <p className={styles.dagHeader}>Log in to load real incident causal chains from Decision Memory.</p>}
            {hasToken && reasoningMemoryQuery.isLoading && <p className={styles.dagHeader}>Loading Decision Memory…</p>}
            {hasToken && reasoningMemoryQuery.isError && <p className={styles.dagHeader}>Could not load Decision Memory (check token).</p>}
            {hasToken && !reasoningMemoryQuery.isLoading && reasoningIncidents.length === 0 && (
              <p className={styles.dagHeader}>No incidents in Decision Memory yet — trigger one from the main dashboard&apos;s Twin Room (Simulate Quality Alert).</p>
            )}

            {reasoningIncidents.length > 0 && (
              <div className={styles.incidentsCard} style={{ marginBottom: "1.5rem" }}>
                <h4 className={styles.incidentsTitle}>Select Incident to Reason About</h4>
                <div className={styles.incidentsList}>
                  {reasoningIncidents.slice(0, 6).map((inc) => (
                    <div
                      key={inc.incidentId}
                      className={`${styles.incidentRow} ${styles.incidentRowClickable} ${
                        inc.incidentId === selectedReasoningId ? styles.incidentRowActive : ""
                      }`}
                      onClick={() => setSelectedReasoningId(inc.incidentId)}
                    >
                      <span className={styles.incLine}>
                        {inc.lineId} — {inc.incidentId.slice(0, 8)} — {inc.causalChain[0]?.description ?? "No causal chain recorded"}
                      </span>
                      <span className={`${styles.incBadge} ${inc.finalState === "Resolved" ? styles.badgeResolved : styles.badgeProgress}`}>
                        {inc.finalState}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {selectedIncident && dagNodes.length > 0 ? (
              <div className={styles.causalLayout}>
                {/* Causal Graph Visualization */}
                <div className={styles.dagBox}>
                  <div className={styles.dagHeader}>BAYESIAN CAUSAL GRAPH — INCIDENT {selectedIncident.incidentId.slice(0, 8)}</div>
                  <div className={styles.dagNodes}>
                    {dagNodes.map((node, i) => (
                      <div key={i} style={{ width: "100%" }}>
                        {i > 0 && (
                          <div className={styles.dagConnector} style={{ marginBottom: "1rem" }}>
                            ⬇ {node.kind === "cause" ? `Causal Conclusion (Weight: ${node.weight!.toFixed(2)})` : "Evidence Link"}
                          </div>
                        )}
                        <div
                          className={`${styles.dagNode} ${
                            node.kind === "source" ? styles.nodeSymptom : node.kind === "cause" ? styles.nodeRoot : styles.nodeIntermediate
                          }`}
                        >
                          <span>
                            {node.kind === "source"
                              ? "SIGNAL SOURCE"
                              : node.kind === "cause"
                              ? `ROOT CAUSE (${(node.weight! * 100).toFixed(0)}% CONFIDENCE)`
                              : "EVIDENCE"}
                          </span>
                          <strong>{node.label}</strong>
                          {node.kind === "cause" && <small>Condition: {selectedIncident.causalChain[0].conditionId}</small>}
                        </div>
                      </div>
                    ))}
                  </div>

                  {alternateCauses.length > 0 && (
                    <div style={{ marginTop: "1.5rem" }}>
                      <div className={styles.dagHeader}>OTHER EVALUATED CANDIDATE CAUSES</div>
                      <div className={styles.incidentsList}>
                        {alternateCauses.map((c) => (
                          <div key={c.conditionId} className={styles.incidentRow}>
                            <span className={styles.incLine}>{c.description}</span>
                            <span
                              className={styles.incBadge}
                              style={{ color: "var(--muted)", background: "transparent", border: "1px solid var(--line)" }}
                            >
                              weight {c.weight.toFixed(2)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* LLM Causal Synthesis Box */}
                <div className={styles.synthesisBox}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                    <h3 style={{ margin: 0 }}>AI CAUSAL SYNTHESIS REPORT</h3>
                    {synthesisQuery.data && (
                      <span
                        className={styles.synthesisStatus}
                        style={
                          synthesisQuery.data.status === "live_llm_generated"
                            ? { color: "#00f0ff", background: "rgba(0,240,255,0.12)", border: "1px solid rgba(0,240,255,0.4)" }
                            : { color: "#8a8a86", background: "rgba(138,138,134,0.12)", border: "1px solid rgba(138,138,134,0.3)" }
                        }
                      >
                        {synthesisQuery.data.status === "live_llm_generated"
                          ? `● LIVE — ${synthesisQuery.data.model_used}`
                          : "○ NOT CONFIGURED"}
                      </span>
                    )}
                  </div>

                  {synthesisQuery.isLoading && <p className={styles.llmText}>Generating root-cause synthesis via local LLM…</p>}
                  {synthesisQuery.isError && <p className={styles.llmText}>Could not reach the causal synthesis endpoint.</p>}
                  {synthesisQuery.data && (
                    <p className={styles.llmText}>
                      {synthesisQuery.data.status === "live_llm_generated"
                        ? `"${synthesisQuery.data.explanation}"`
                        : "No local LLM is configured on this backend (LOCAL_LLM_ENABLED), so there's no generated narrative — showing the real evaluated evidence chain below instead of a fabricated summary."}
                    </p>
                  )}

                  <div className={styles.evidenceChain}>
                    <span>EVIDENCE CHAIN EVALUATED (Primary Cause):</span>
                    <ul>
                      {selectedIncident.causalChain[0].evidencePath.length > 0 ? (
                        selectedIncident.causalChain[0].evidencePath.map((p, i) => <li key={i}>✔ {p}</li>)
                      ) : (
                        <li>No evidence path recorded for this condition.</li>
                      )}
                    </ul>
                  </div>
                </div>
              </div>
            ) : (
              hasToken &&
              reasoningIncidents.length > 0 && <p className={styles.dagHeader}>Selected incident has no recorded causal chain.</p>
            )}
          </div>
        )}

        {/* TAB 2: AUTONOMY (POLICY STUDIO + GOVERNANCE MATRIX) */}
        {activeTab === "autonomy" && (
          <div className={styles.tabView}>
            <div className={styles.viewHeader}>
              <h2>🛡️ TIERS OF AUTONOMY GOVERNANCE MATRIX</h2>
              <p>Risk Boundary Locks ($ Financial Exposure × Confidence Score)</p>
            </div>

            <div className={styles.rulesTable}>
              <div className={styles.tableHeader}>
                <span>GOVERNANCE TIER</span>
                <span>FINANCIAL LIMIT</span>
                <span>CONFIDENCE GATE</span>
                <span>SYSTEM POLICY ACTION</span>
                <span>CURRENT STATUS</span>
              </div>
              {GOVERNANCE_RULES.map((rule) => (
                <div key={rule.tier} className={styles.tableRow}>
                  <strong className={styles.tierName}>{rule.tier} — {rule.name}</strong>
                  <span>{rule.costLimit}</span>
                  <span>{rule.confGate}</span>
                  <span className={styles.actionDesc}>{rule.action}</span>
                  <span
                    className={styles.tierStatus}
                    style={{
                      color: rule.status.includes("REQUIRED") ? "#d7ff3e" : rule.status === "ACTIVE" ? "#00f0ff" : "#8a8a86"
                    }}
                  >
                    ● {rule.status}
                  </span>
                </div>
              ))}
            </div>

            {/* Interactive Policy Simulator */}
            <div className={styles.simulatorBox}>
              <h3>INTERACTIVE POLICY SIMULATOR</h3>
              <div className={styles.simControls}>
                <div>
                  <label>Estimated Action Cost: <strong>${simCost}</strong></label>
                  <input
                    type="range"
                    min="100"
                    max="10000"
                    step="100"
                    value={simCost}
                    onChange={(e) => setSimCost(Number(e.target.value))}
                  />
                </div>
                <div>
                  <label>AI Diagnosis Confidence: <strong>{simConf}%</strong></label>
                  <input
                    type="range"
                    min="40"
                    max="100"
                    step="1"
                    value={simConf}
                    onChange={(e) => setSimConf(Number(e.target.value))}
                  />
                </div>
              </div>

              <div className={styles.simResult} style={{ borderColor: calculatedTier.color }}>
                <span>CALCULATED POLICY DESTINATION:</span>
                <h4 style={{ color: calculatedTier.color }}>{calculatedTier.tier}: {calculatedTier.label}</h4>
              </div>
            </div>

            {/* Migrated from main dashboard (/governance, /policy-studio) — real
                backend-wired governance matrix, RBAC rules, no-code rule builder,
                and KPIEngine what-if simulator, rendered as-is (own design system). */}
            <div className={styles.embeddedSectionLabel}>LIVE BACKEND GOVERNANCE — MIGRATED FROM MAIN DASHBOARD</div>
            <div className={styles.embeddedPage}>
              <GovernancePolicyPage />
            </div>
            <div className={styles.embeddedPage} style={{ marginTop: "1.5rem" }}>
              <PolicyStudioPage />
            </div>
          </div>
        )}

        {/* TAB 3: AGENTS (SPECIALIST SWARM AGENT REGISTRY & TOPOLOGY) */}
        {activeTab === "agents" && (
          <div className={styles.tabView}>
            <div className={styles.viewHeader}>
              <h2>🤖 SPECIALIST SWARM AGENT REGISTRY</h2>
              <p>Live agent topology, stage roster & event stream — migrated from /agents/network</p>
            </div>
            <div className={styles.embeddedPage}>
              <AgentNetworkPage />
            </div>
          </div>
        )}

        {/* TAB 4: HUB (ENTERPRISE INTEGRATIONS) */}
        {activeTab === "hub" && (
          <div className={styles.tabView}>
            <div className={styles.viewHeader}>
              <h2>🔌 ENTERPRISE INTEGRATIONS HUB</h2>
              <p>ServiceNow, SAP ERP, ADOS Capabilities & Kafka bus status — migrated from /integrations</p>
            </div>
            <div className={styles.embeddedPage}>
              <IntegrationsPage />
            </div>
          </div>
        )}

        {/* TAB 5: COPILOT (EXECUTIVE WATSONX.AI ASSISTANT) */}
        {activeTab === "copilot" && (
          <div className={styles.tabView}>
            <div className={styles.viewHeader}>
              <h2>💬 EXECUTIVE ADOS COPILOT</h2>
              <p>Natural language operational query engine, grounded in documentation/08-12&apos;s governance policy documents</p>
            </div>

            <div className={styles.chatContainer}>
              <div className={styles.messagesBox}>
                {chatMessages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`${styles.chatMsg} ${msg.sender === "user" ? styles.msgUser : styles.msgAi}`}
                    style={msg.pending ? { opacity: 0.6, fontStyle: "italic" } : undefined}
                  >
                    <span className={styles.msgSender}>{msg.sender === "user" ? "DIRECTOR" : "WATSONX COPILOT"}</span>
                    <p style={{ whiteSpace: "pre-wrap" }}>{msg.text}</p>
                  </div>
                ))}
              </div>

              <form onSubmit={handleChatSubmit} className={styles.chatForm}>
                <input
                  type="text"
                  placeholder="Ask copilot (e.g. Who can approve a Tier 2 decision?)"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  disabled={chatBusy}
                />
                <button type="submit" disabled={chatBusy}>{chatBusy ? "THINKING…" : "SEND QUERY ↗"}</button>
              </form>
            </div>
          </div>
        )}

      </main>
    </div>
  );
}
