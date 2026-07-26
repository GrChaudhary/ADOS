// ADOS Phase 5 narrative demo page — plain JS, no build step.
// Self-contained: does NOT reuse app.js (different DOM structure, and
// app.js's DOMContentLoaded handler assumes ops-dashboard-only elements).
// Shares the same auth token as the ops dashboard via the same localStorage
// key, so a token entered on either page works on both.

const TOKEN_KEY = "ados_service_token";

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}
function setToken(value) {
  localStorage.setItem(TOKEN_KEY, value);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Authorization": `Bearer ${getToken()}`,
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${path}: ${text}`);
  }
  return response.status === 204 ? null : response.json();
}

// ---------------------------------------------------------------------
// View routing
// ---------------------------------------------------------------------

function showView(name) {
  document.querySelectorAll(".view").forEach((el) => { el.hidden = el.id !== `view-${name}`; });
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
  if (name === "home") loadHomeData();
  if (name === "executive" && typeof renderExecutiveMode === "function") renderExecutiveMode();
  if (name === "ibm" && typeof renderIbmWorkflowView === "function") renderIbmWorkflowView();
}

// ---------------------------------------------------------------------
// Home / Mission Control
// ---------------------------------------------------------------------

// Session-local state: incidents started from this page, and a line-status
// override while one of them is still in flight (the real DigitalTwinStore
// doesn't yet flip a line's status on incident start/resolve — see
// docs/PHASE5B_ANTIGRAVITY_HANDOFF.md's note on this — so the demo page
// tracks "this line has an active incident" itself, honestly, rather than
// claiming the backend reports it).
const recentIncidents = []; // [{incidentId, lineId, status, detectedAt}]
const activeIncidentLines = new Set();

async function loadHomeData() {
  if (!getToken()) {
    document.getElementById("kpiProductionHealth").textContent = "—";
    document.getElementById("kpiAutonomous").textContent = "—";
    document.getElementById("kpiRevenue").textContent = "—";
    document.getElementById("homeLineStrip").innerHTML = `<div class="empty">Enter a service token above to load live data.</div>`;
    return;
  }

  try {
    const kpis = await api("/executive/kpis");
    const health = kpis.totalIncidents > 0
      ? `${Math.round((kpis.resolvedIncidents / kpis.totalIncidents) * 100)}%`
      : "100%";
    document.getElementById("kpiProductionHealth").textContent = health;
    const tier0 = kpis.tierDistribution?.["Tier 0 (Autonomous)"] ?? 0;
    document.getElementById("kpiAutonomous").textContent = tier0;
    document.getElementById("kpiRevenue").textContent = `$${Math.round(kpis.revenueProtectedUsd).toLocaleString()}`;
  } catch (e) {
    console.error("Failed to load KPIs", e);
  }

  document.getElementById("kpiOpenIncidents").textContent =
    recentIncidents.filter((i) => i.status === "in_progress").length;

  await loadLineStrip();
  renderRecentIncidents();
}

async function loadLineStrip() {
  const container = document.getElementById("homeLineStrip");
  try {
    const lines = await api("/digital-twin/lines");
    container.innerHTML = "";
    lines.forEach((line) => {
      const overridden = activeIncidentLines.has(line.lineId);
      const status = overridden ? "DEGRADED" : line.status;
      const dotClass = status === "OPERATIONAL" ? "operational" : (status === "DEGRADED" ? "degraded" : "stopped");
      const icon = status === "OPERATIONAL" ? "🟢" : (status === "DEGRADED" ? "🔴" : "⚫");
      const chip = document.createElement("div");
      chip.className = "line-chip";
      chip.innerHTML = `<span class="line-dot ${dotClass}"></span> ${line.lineId} ${icon}`;
      container.appendChild(chip);
    });
  } catch (e) {
    container.innerHTML = `<div class="empty">Could not load digital twin (check token).</div>`;
  }
}

function renderRecentIncidents() {
  const container = document.getElementById("recentIncidents");
  if (recentIncidents.length === 0) {
    container.innerHTML = `<div class="empty">No incidents yet this session.</div>`;
  } else {
    container.innerHTML = "";
    [...recentIncidents].reverse().forEach((inc) => {
      const row = document.createElement("div");
      row.className = "recent-item";
      const badgeClass = inc.status === "in_progress" ? "stage-running" : (inc.status === "Resolved" ? "stage-completed" : "failed");
      row.innerHTML = `<span>${inc.lineId} — ${inc.incidentId.slice(0, 8)}</span><span class="badge ${badgeClass}">${inc.status}</span>`;
      row.addEventListener("click", () => openWorkspace(inc.incidentId, inc.lineId));
      container.appendChild(row);
    });
  }
  updateSimulateButtonState();
}

function updateSimulateButtonState() {
  // Approving is a required human step in this orchestrator (Tier 1/2
  // decisions block on ApprovalQueue) — an unapproved incident holds its
  // production line's preemption lock indefinitely (orchestrate/preemption.py),
  // so a second "Simulate Quality Alert" click on the same line before the
  // first is resolved would just hang forever with no visible feedback.
  // Disable the button instead of letting a demo run into that silently.
  const btn = document.getElementById("simulateAlertBtn");
  const busy = recentIncidents.some((i) => i.status === "in_progress");
  btn.disabled = busy;
  btn.title = busy ? "An incident is already in progress — resolve or approve it first." : "";
}

async function simulateQualityAlert() {
  const btn = document.getElementById("simulateAlertBtn");
  btn.disabled = true;
  try {
    const body = {
      plant_id: "FAC-P1-L2",
      line_id: "Line 2",
      part_number: "MH-100",
      vision_data: { measured_bore_diameter_mm: 45.085 },
      priority: {
        safety_impact: 0.7,
        customer_impact: 0.8,
        line_down_cost_per_hour_usd: 15000,
        production_priority: 0.75,
        is_systemic: false,
      },
    };
    const result = await api("/incidents", { method: "POST", body: JSON.stringify(body) });
    const incidentId = result.incident_id;

    recentIncidents.push({ incidentId, lineId: "Line 2", status: "in_progress", detectedAt: new Date().toISOString() });
    activeIncidentLines.add("Line 2");
    loadHomeData();

    document.getElementById("viewIncidentBtn").onclick = () => {
      document.getElementById("qualityAlertModal").hidden = true;
      openWorkspace(incidentId, "Line 2");
    };
    document.getElementById("qualityAlertModal").hidden = false;
  } catch (e) {
    alert(`Could not start incident: ${e.message}`);
    updateSimulateButtonState(); // re-enable on failure — no incident was actually started
  }
  // On success, updateSimulateButtonState() (called via loadHomeData() above)
  // is the single source of truth for the button's disabled state — it stays
  // disabled until this incident resolves, not just for the POST's duration.
}

// ---------------------------------------------------------------------
// Incident Workspace
// ---------------------------------------------------------------------

let workspaceState = null; // { incidentId, lineId, eventSource, pollTimer, approveShown }

function openWorkspace(incidentId, lineId) {
  teardownWorkspace();

  workspaceState = { incidentId, lineId, eventSource: null, pollTimer: null, approveShown: false, seenEventIds: new Set() };

  document.getElementById("workspaceTitle").textContent = `Motor Housing Incident — ${incidentId.slice(0, 8)}`;
  document.getElementById("workspaceStatusBadge").textContent = "In Progress";
  document.getElementById("workspaceStatusBadge").className = "badge stage-running";
  document.getElementById("recoveryBanner").hidden = true;

  ["overview", "evidence", "reasoning", "recommendations", "execution", "audit"].forEach((tab) => {
    const content = document.getElementById(`${tab}Content`);
    if (tab !== "overview") content.innerHTML = `<div class="empty">Waiting for live data…</div>`;
  });
  renderOverviewTab({ status: "in_progress" });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === "overview");
    btn.onclick = () => switchTab(btn.dataset.tab);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-overview"));

  showView("workspace");

  // Open the live stream FIRST, then backfill anything that already fired
  // before we subscribed (event_bus.stream() has no replay — a fast-resolving
  // incident can complete every agent stage before a human even finishes
  // clicking through the "Quality Alert" popup, so most events would
  // otherwise be missed entirely). Opening SSE before backfilling means the
  // backfill can only ever double-report an event (harmless, deduped by
  // eventId below), never lose one to the gap between the two calls.
  const token = getToken();
  workspaceState.eventSource = new EventSource(
    `/events/stream?token=${encodeURIComponent(token)}&incident_id=${encodeURIComponent(incidentId)}`
  );
  workspaceState.eventSource.onmessage = (e) => {
    try {
      handleIncidentEvent(JSON.parse(e.data));
    } catch (err) {
      console.error("Failed to parse SSE event", err);
    }
  };

  api(`/events?incident_id=${encodeURIComponent(incidentId)}`)
    .then((events) => events.forEach(handleIncidentEvent))
    .catch((err) => console.error("Failed to backfill incident events", err));

  workspaceState.pollTimer = setInterval(() => pollIncidentStatus(incidentId), 1000);
  pollIncidentStatus(incidentId);
}

function teardownWorkspace() {
  if (workspaceState?.eventSource) workspaceState.eventSource.close();
  if (workspaceState?.pollTimer) clearInterval(workspaceState.pollTimer);
  workspaceState = null;
}

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tabName));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tabName}`));
}

function appendAuditRow(envelope) {
  const container = document.getElementById("auditContent");
  const emptyEl = container.querySelector(".empty");
  if (emptyEl) container.innerHTML = "";
  const row = document.createElement("div");
  row.className = "timeline-item";
  row.innerHTML = `
    <div class="timeline-header">
      <span class="timeline-stage">${envelope.eventType}</span>
      <span class="badge">${envelope.producedBy || ""}</span>
    </div>
    <div class="timeline-detail">${envelope.occurredAt || ""}</div>
  `;
  container.insertBefore(row, container.firstChild);
}

function handleIncidentEvent(envelope) {
  if (!workspaceState || workspaceState.incidentId !== envelope.incidentId) return;
  if (workspaceState.seenEventIds.has(envelope.eventId)) return;
  workspaceState.seenEventIds.add(envelope.eventId);

  appendAuditRow(envelope);

  const payload = envelope.payload || {};
  const agentId = payload.agent_id || payload.agentId || "";

  if (envelope.eventType === "AgentCompleted") {
    if (agentId.includes("vision-spec")) renderEvidenceVision(payload);
    else if (agentId.includes("cad-spec")) renderEvidenceCad(payload);
    else if (agentId.includes("causal-isolation")) renderReasoning(payload);
    else if (agentId.includes("impact-simulation")) renderRecommendationsFromLive(payload);
  } else if (envelope.eventType === "CapabilityInvocationStarted") {
    renderChecklist(payload, "started");
  } else if (envelope.eventType === "CapabilityInvocationCompleted") {
    renderChecklist(payload, "completed");
  }
}

function renderOverviewTab(extra) {
  const container = document.getElementById("overviewContent");
  const rows = [
    ["Incident", workspaceState.incidentId],
    ["Line", workspaceState.lineId],
    ["Status", extra.status || "in_progress"],
  ];
  if (extra.confidence !== undefined) rows.push(["Confidence", `${Math.round(extra.confidence * 100)}%`]);
  if (extra.approvedBy) rows.push(["Approved by", extra.approvedBy]);
  container.innerHTML = rows.map(([k, v]) => `<div class="kv-row"><span class="k">${k}</span><span>${v}</span></div>`).join("");
}

function renderEvidenceVision(payload) {
  const container = document.getElementById("evidenceContent");
  const emptyEl = container.querySelector(".empty");
  if (emptyEl) container.innerHTML = "";
  const r = payload.result || {};
  const div = document.createElement("div");
  div.innerHTML = `
    <div class="kv-row"><span class="k">Defect Detected</span><span>${r.defect_detected ? "Yes" : "No"}</span></div>
    <div class="kv-row"><span class="k">Measured Bore Diameter</span><span>${r.measured_value ?? "—"} mm</span></div>
    <div class="kv-row"><span class="k">Deviation</span><span>${r.deviation_mm ?? "—"} mm</span></div>
  `;
  container.appendChild(div);
}

function renderEvidenceCad(payload) {
  const container = document.getElementById("evidenceContent");
  const r = payload.result || {};
  const range = r.tolerance_range || [];
  const div = document.createElement("div");
  div.innerHTML = `
    <div class="kv-row"><span class="k">Spec Violation</span><span>${r.is_violation ? "Yes (" + r.violation_direction + ")" : "No"}</span></div>
    <div class="kv-row"><span class="k">Allowed Range</span><span>${range[0] ?? "—"} – ${range[1] ?? "—"} mm</span></div>
  `;
  container.appendChild(div);
}

function renderReasoning(payload) {
  const container = document.getElementById("reasoningContent");
  container.innerHTML = "";
  const r = payload.result || {};
  const top = document.createElement("div");
  top.className = "kv-row";
  top.innerHTML = `<span class="k">Primary Root Cause</span><span>${r.primary_root_cause ?? "—"}</span>`;
  container.appendChild(top);
  (r.ranked_causes || []).forEach((c) => {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.innerHTML = `<span class="k">${c.name}</span><span>weight ${c.weight}</span>`;
    container.appendChild(row);
  });
}

function starString(overallScore) {
  const stars = Math.max(1, Math.min(5, Math.round(overallScore * 5)));
  return "★".repeat(stars) + "☆".repeat(5 - stars);
}

function renderOptionCards(options) {
  const container = document.getElementById("recommendationsContent");
  container.innerHTML = "";
  const grid = document.createElement("div");
  grid.className = "option-grid";

  const maxCost = Math.max(...options.map((o) => o.estimated_cost_usd ?? o.estimatedCostUsd ?? 0));

  options.forEach((o, idx) => {
    const cost = o.estimated_cost_usd ?? o.estimatedCostUsd ?? 0;
    const downtime = o.downtime_minutes ?? o.downtimeMinutes ?? 0;
    const risk = o.quality_risk_score ?? o.qualityRiskScore ?? 0;
    const score = o.overall_score ?? o.overallScore ?? 0;
    const name = o.name ?? "Option";
    const rec = o.recommendation ?? "FEASIBLE";
    const letter = o.letter ?? String.fromCharCode(65 + idx);
    const savings = Math.max(0, maxCost - cost);

    const card = document.createElement("div");
    card.className = `option-card${rec === "TOP_PICK" ? " recommended" : ""}`;
    card.innerHTML = `
      <div><span class="option-letter">${letter}</span><strong>${name}</strong></div>
      <div class="option-stars">${starString(score)}</div>
      <div class="option-metrics">
        Cost: $${cost.toLocaleString()}<br/>
        Downtime: ${downtime} min<br/>
        Quality Risk: ${Math.round(risk * 100)}%<br/>
        Savings vs. costliest: $${savings.toLocaleString()}
      </div>
    `;
    grid.appendChild(card);
  });

  container.appendChild(grid);

  if (!workspaceState.approveShown) {
    const bar = document.createElement("div");
    bar.className = "approve-bar";
    bar.innerHTML = `<button type="button" class="primary-btn" id="approveBtn">Approve Recommended Option</button>`;
    container.appendChild(bar);
    document.getElementById("approveBtn").onclick = approveCurrentIncident;
  }
}

function renderRecommendationsFromLive(payload) {
  const r = payload.result || {};
  if (Array.isArray(r.ranked_options) && r.ranked_options.length > 0) {
    renderOptionCards(r.ranked_options);
  }
}

async function approveCurrentIncident() {
  const btn = document.getElementById("approveBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Approving…"; }
  try {
    await api(`/incidents/${workspaceState.incidentId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: "Emma Rodriguez (Quality Engineer)" }),
    });
  } catch (e) {
    alert(`Approval failed: ${e.message}`);
    if (btn) { btn.disabled = false; btn.textContent = "Approve Recommended Option"; }
  }
}

function renderChecklist(payload, phase) {
  const container = document.getElementById("executionContent");
  const emptyEl = container.querySelector(".empty");
  if (emptyEl) container.innerHTML = "";

  let card = container.querySelector(".checklist-card");
  if (!card) {
    card = document.createElement("div");
    card.className = "checklist-card";
    container.appendChild(card);
  }

  const steps = payload.executionSteps || [];
  const capability = payload.capability || "Capability";

  if (phase === "started") {
    const itemsHtml = steps.map((s) => `<div class="checklist-item"><span class="checklist-icon pending">&#9679;</span><span>${s}</span></div>`).join("");
    card.innerHTML = `
      <div class="timeline-header"><span class="timeline-stage">${capability}</span><span class="badge stage-running">In Progress</span></div>
      ${itemsHtml}
    `;
  } else {
    const succeeded = payload.status === "succeeded";
    const icon = succeeded ? "&#10003;" : "&#10007;";
    const iconClass = succeeded ? "done" : "failed-icon";
    const badgeHtml = succeeded ? '<span class="badge stage-completed">Completed</span>' : '<span class="badge failed">Failed</span>';
    const itemsHtml = steps.map((s) => `<div class="checklist-item"><span class="checklist-icon ${iconClass}">${icon}</span><span>${s}</span></div>`).join("");
    card.innerHTML = `
      <div class="timeline-header"><span class="timeline-stage">${capability}</span>${badgeHtml}</div>
      ${itemsHtml}
    `;
  }
}

async function pollIncidentStatus(incidentId) {
  if (!workspaceState || workspaceState.incidentId !== incidentId) return;
  let record;
  try {
    record = await api(`/incidents/${incidentId}`);
  } catch (e) {
    return;
  }

  if (record.awaitingApproval && !workspaceState.approveShown) {
    workspaceState.approveShown = true;
    // Recommendations tab already shows the Approve button once the
    // impact_simulation event has rendered options; if it hasn't arrived
    // yet (race), the button will appear as soon as it does.
  }

  if (record.finalState) {
    // Terminal — full IncidentRecord.
    clearInterval(workspaceState.pollTimer);
    if (workspaceState.eventSource) workspaceState.eventSource.close();

    document.getElementById("workspaceStatusBadge").textContent = record.finalState;
    document.getElementById("workspaceStatusBadge").className =
      "badge " + (record.finalState === "Resolved" ? "stage-completed" : "failed");

    renderOverviewTab({
      status: record.finalState,
      confidence: record.confidence,
      approvedBy: record.approvedBy,
    });

    if (record.finalState === "Resolved") {
      document.getElementById("recoveryBanner").hidden = false;
      document.getElementById("recoveryDowntime").textContent = `${record.actualDowntimeMin ?? "—"} min`;
      document.getElementById("recoveryConfidence").textContent = `${Math.round((record.confidence ?? 0) * 100)}%`;
      document.getElementById("recoveryTier").textContent = ["Tier 0 · Autonomous", "Tier 1 · Approved", "Tier 2 · Executive"][record.policyTier] || "";
    }

    const recEntry = recentIncidents.find((i) => i.incidentId === incidentId);
    if (recEntry) recEntry.status = record.finalState;
    activeIncidentLines.delete(workspaceState.lineId);
    renderRecentIncidents();

    // Historical/authoritative comparison (Phase 3 REST endpoint) — the
    // live SSE-rendered cards above already show this for the in-flight
    // case; this just confirms it's consistent once finalized.
    try {
      const comparison = await api(`/executive/incidents/${incidentId}/options`);
      if (comparison.options?.length) renderOptionCards(comparison.options);
    } catch (e) {
      // fine if this incident predates alternatives tracking
    }
  }
}

// ---------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const tokenInput = document.getElementById("tokenInput");
  tokenInput.value = getToken();
  tokenInput.addEventListener("change", () => {
    setToken(tokenInput.value);
    loadHomeData();
  });

  document.querySelectorAll("[data-view]").forEach((el) => {
    el.addEventListener("click", () => showView(el.dataset.view));
  });

  document.getElementById("simulateAlertBtn").addEventListener("click", simulateQualityAlert);
  document.getElementById("backToHomeBtn").addEventListener("click", () => {
    teardownWorkspace();
    showView("home");
  });

  showView("home");
});
