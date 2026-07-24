// ADOS approval surface + executive dashboard — plain JS, no build step.
// Talks to the backend on the same origin (see backend/app/main.py mounting
// this directory as static files), auth via a bearer token kept in
// localStorage (docs/009-security.md's MVP shared-secret auth, same token
// as SERVICE_AUTH_TOKEN).

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

function tierBadge(tier) {
  const n = typeof tier === "number" ? tier : parseInt(tier, 10);
  const labels = ["Tier 0", "Tier 1", "Tier 2"];
  return `<span class="badge tier${n}">${labels[n] ?? tier}</span>`;
}

function stateBadge(state) {
  const cls = { Resolved: "resolved", Failed: "failed", Preempted: "preempted" }[state] || "";
  return `<span class="badge ${cls}">${state}</span>`;
}

// ---------------------------------------------------------------------
// Start Incident
// ---------------------------------------------------------------------

async function startIncident(event) {
  event.preventDefault();
  const form = event.target;
  const body = {
    plant_id: form.plant_id.value,
    line_id: form.line_id.value,
    part_number: form.part_number.value,
    vision_data: { measured_bore_diameter_mm: parseFloat(form.measured_value.value) },
    priority: {
      safety_impact: parseFloat(form.safety_impact.value),
      customer_impact: parseFloat(form.customer_impact.value),
      line_down_cost_per_hour_usd: parseFloat(form.line_down_cost.value),
      production_priority: parseFloat(form.production_priority.value),
      is_systemic: form.is_systemic.checked,
    },
  };
  const statusEl = document.getElementById("startIncidentStatus");
  try {
    const result = await api("/incidents", { method: "POST", body: JSON.stringify(body) });
    statusEl.textContent = `Started ${result.incident_id}`;
    statusEl.className = "muted";
    refreshAll();
  } catch (e) {
    statusEl.textContent = e.message;
    statusEl.className = "muted";
  }
}

// ---------------------------------------------------------------------
// Pending Approvals
// ---------------------------------------------------------------------

async function decide(incidentId, action) {
  const approvedBy = prompt("Your name/ID:", "ops-lead");
  if (!approvedBy) return;
  await api(`/incidents/${incidentId}/${action}`, {
    method: "POST",
    body: JSON.stringify({ approved_by: approvedBy }),
  });
  refreshAll();
}

async function refreshApprovals() {
  const el = document.getElementById("approvalsList");
  try {
    const pending = await api("/approvals");
    if (pending.length === 0) {
      el.innerHTML = '<div class="empty">No incidents awaiting approval.</div>';
      return;
    }
    el.innerHTML = pending.map((p) => `
      <div class="card">
        <div class="row">
          <strong>${p.capability}</strong>
          ${tierBadge(p.policyTier)}
        </div>
        <div class="muted">${p.summary}</div>
        <div class="muted">confidence ${p.confidence} · incident ${p.incidentId}</div>
        <div>
          <button class="small" onclick="decide('${p.incidentId}','approve')">Approve</button>
          <button class="small danger" onclick="decide('${p.incidentId}','reject')">Reject</button>
          <button class="small secondary" onclick="decide('${p.incidentId}','escalate')">Escalate</button>
        </div>
      </div>
    `).join("");
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------
// Recent Incidents (audit trail)
// ---------------------------------------------------------------------

async function refreshIncidents() {
  const el = document.getElementById("incidentsList");
  try {
    const records = await api("/incidents?limit=20");
    if (records.length === 0) {
      el.innerHTML = '<div class="empty">No resolved incidents yet.</div>';
      return;
    }
    el.innerHTML = records.slice().reverse().map((r) => `
      <div class="card">
        <div class="row">
          <strong>${r.lineId}</strong>
          ${stateBadge(r.finalState)}
        </div>
        <div class="muted">${r.capabilityInvoked || "—"} · ${r.capabilityStatus || ""}</div>
        <div class="muted">cost $${r.actualCostUsd ?? "—"} · downtime ${r.actualDowntimeMin ?? "—"}min</div>
        <div class="muted">${(r.causalChain || []).map((c) => c.description).join(", ") || "no causal chain"}</div>
      </div>
    `).join("");
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------
// Executive KPIs
// ---------------------------------------------------------------------

async function refreshKpis() {
  const el = document.getElementById("kpiGrid");
  try {
    const k = await api("/executive/kpis");
    el.innerHTML = `
      <div class="kpi-tile"><div class="value">${k.mttrAvgMinutes}m</div><div class="label">MTTR avg</div></div>
      <div class="kpi-tile"><div class="value">$${k.revenueProtectedUsd}</div><div class="label">Revenue protected</div></div>
      <div class="kpi-tile"><div class="value">${(k.autonomyIndex * 100).toFixed(0)}%</div><div class="label">Autonomy index</div></div>
      <div class="kpi-tile"><div class="value">${(k.recommendationAcceptanceRate * 100).toFixed(0)}%</div><div class="label">Rec. acceptance</div></div>
      <div class="kpi-tile"><div class="value">${k.totalIncidents}</div><div class="label">Total incidents</div></div>
      <div class="kpi-tile"><div class="value">${k.resolvedIncidents}/${k.failedIncidents}</div><div class="label">Resolved/Failed</div></div>
    `;
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

async function refreshRecommendations() {
  const el = document.getElementById("recommendationsList");
  try {
    const recs = await api("/executive/recommendations");
    if (recs.length === 0) {
      el.innerHTML = '<div class="empty">No strategic recommendations yet.</div>';
      return;
    }
    el.innerHTML = recs.map((r) => `
      <div class="card">
        <div class="row"><strong>${r.title || r.recommendationId || "Recommendation"}</strong> <span class="badge">${r.impact_level || ""}</span></div>
        <div class="muted">${r.summary || ""}</div>
      </div>
    `).join("");
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

async function refreshRisk() {
  const el = document.getElementById("riskList");
  try {
    const signals = await api("/executive/risk");
    if (signals.length === 0) {
      el.innerHTML = '<div class="empty">No active risk signals.</div>';
      return;
    }
    el.innerHTML = signals.map((r) => `
      <div class="card">
        <div class="row"><strong>${r.lineId || r.plantId}</strong> <span class="badge">${(r.risk_score ?? 0).toFixed(2)}</span></div>
        <div class="muted">${r.risk_level || ""} — ${r.primaryRiskDriver || ""}</div>
      </div>
    `).join("");
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

async function askCopilot(event) {
  event.preventDefault();
  const query = document.getElementById("copilotQuery").value;
  const answerEl = document.getElementById("copilotAnswer");
  answerEl.textContent = "Thinking...";
  try {
    const response = await api("/executive/copilot/ask", { method: "POST", body: JSON.stringify({ query }) });
    const citations = (response.dataCitations || [])
      .map((c) => `${c.source}: ${c.metric ?? ""} ${c.value ?? ""}`)
      .join(" · ");
    answerEl.innerHTML = `
      <div class="copilot-answer">${response.answer}</div>
      <div class="citations">confidence ${response.confidence} · ${citations}</div>
    `;
  } catch (e) {
    answerEl.textContent = e.message;
  }
}

// ---------------------------------------------------------------------
// Phase 4 — Decision Memory Search
// ---------------------------------------------------------------------

async function searchDecisionMemory(event) {
  event.preventDefault();
  const el = document.getElementById("memorySearchResults");
  el.innerHTML = '<div class="empty">Searching…</div>';
  try {
    const body = {
      defectType: document.getElementById("memoryDefectType").value || undefined,
      plantId: document.getElementById("memoryPlantId").value || undefined,
      limit: 5,
    };
    const res = await api("/memory/search", { method: "POST", body: JSON.stringify(body) });
    if (res.totalMatches === 0) {
      el.innerHTML = '<div class="empty">No matching precedents found.</div>';
      return;
    }
    el.innerHTML = `<div class="muted" style="margin-bottom:8px;">${res.totalMatches} historical match(es)</div>` +
      res.records.map((r, i) => `
        <div class="card">
          <div class="row">
            <strong>${r.incidentId}</strong>
            ${stateBadge(r.finalState)}
          </div>
          <div class="muted">relevance ${res.relevanceScores[i]} · MTTR ${r.actualDowntimeMin ?? "—"}min · ${r.lineId || ""}</div>
          <div class="muted">${(r.causalChain || []).map((c) => c.description).join(", ") || "no causal chain"}</div>
        </div>
      `).join("");
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------
// Phase 4B — Causal Graph Recalibration (Learning Engine)
// ---------------------------------------------------------------------

async function runRecalibration() {
  const el = document.getElementById("recalibrationResult");
  el.innerHTML = '<div class="empty">Replaying audit trail…</div>';
  try {
    const res = await api("/learning/recalibration");
    const rows = res.weightAdjustments.map((adj) => {
      const deltaClass = adj.delta >= 0 ? "delta-up" : "delta-down";
      const sign = adj.delta >= 0 ? "+" : "";
      return `
        <div class="entry">
          <span>${adj.condition_id} <span class="muted">(${adj.incident_id})</span></span>
          <span>${adj.previous_weight} &rarr; ${adj.new_weight} <span class="${deltaClass}">(${sign}${adj.delta})</span></span>
        </div>
      `;
    }).join("");
    el.innerHTML = `
      <div class="muted" style="margin-bottom:8px;">${res.recordsProcessed} record(s) replayed · ${res.edgesUpdated} edge(s) recalibrated</div>
      <div class="weight-log">${rows}</div>
    `;
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------
// Phase 4B — Memory-Augmented Agent RAG Demo
// ---------------------------------------------------------------------

async function runRagDemo() {
  const el = document.getElementById("ragDemoResult");
  el.innerHTML = '<div class="empty">Running agent reasoning…</div>';
  try {
    const out = await api("/learning/memory-rag-demo", { method: "POST", body: JSON.stringify({}) });
    const evidenceRows = out.evidence.map((ev) => `
      <div class="entry"><span class="source">[${ev.sourceType}]</span>${ev.description}</div>
    `).join("");
    el.innerHTML = `
      <div class="card">
        <div class="row"><strong>${out.result.primary_root_cause}</strong></div>
        <div class="muted">confidence ${out.confidence} (memory-boosted)</div>
      </div>
      <div class="evidence-list">${evidenceRows}</div>
    `;
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------
// Phase 4B — Autonomy Tier 0 Promotion Candidates
// ---------------------------------------------------------------------

async function refreshPromotionCandidates() {
  const el = document.getElementById("promotionCandidates");
  try {
    const candidates = await api("/learning/promotion-candidates");
    if (candidates.length === 0) {
      el.innerHTML = '<div class="empty">No decision categories evaluated yet.</div>';
      return;
    }
    el.innerHTML = candidates.map((c) => `
      <div class="card">
        <div class="row">
          <strong>${c.decisionClassName}</strong>
          <span class="badge ${c.isEligible ? "eligible" : "pending-data"}">${c.isEligible ? "Eligible for Tier 0" : "Needs more data"}</span>
        </div>
        <div class="muted">${c.sampleVolume} incident(s) · ${(c.operatorAcceptanceRate * 100).toFixed(0)}% acceptance · avg confidence ${c.avgConfidence}</div>
        <div class="muted">${c.promotionRationale}</div>
      </div>
    `).join("");
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------
// Phase 1 — Digital Twin Live Line Status
// ---------------------------------------------------------------------

async function refreshDigitalTwinLines() {
  const el = document.getElementById("digitalTwinLines");
  if (!el) return;
  try {
    const lines = await api("/digital-twin/lines");
    if (!lines || lines.length === 0) {
      el.innerHTML = '<div class="empty">No line status data available.</div>';
      return;
    }
    el.innerHTML = lines.map((l) => {
      const stClass = l.status === "OPERATIONAL" ? "status-operational" : (l.status === "DEGRADED" ? "status-degraded" : "status-stopped");
      const speed = l.currentSpeedUnitsPerHr ? `${l.currentSpeedUnitsPerHr} u/hr` : "Idle";
      return `
        <div class="dt-line-card">
          <div class="dt-line-info">
            <div class="dt-line-id">${l.lineId}</div>
            <div class="dt-line-sku">Active: ${l.activeProductSku} · ${speed}</div>
          </div>
          <span class="badge ${stClass}">${l.status}</span>
        </div>
      `;
    }).join("");
  } catch (e) {
    el.innerHTML = `<div class="empty">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------------
// Phase 2 — SSE Live Agent Timeline
// ---------------------------------------------------------------------

let eventSource = null;

function initEventStream() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  const token = getToken();
  const statusEl = document.getElementById("sseStreamStatus");
  const timelineEl = document.getElementById("agentTimeline");
  if (!token || !statusEl || !timelineEl) return;

  statusEl.textContent = "Connecting…";
  statusEl.className = "badge live-pulse";

  eventSource = new EventSource(`/events/stream?token=${encodeURIComponent(token)}`);

  eventSource.onopen = () => {
    statusEl.textContent = "LIVE";
    statusEl.className = "badge resolved";
  };

  eventSource.onerror = () => {
    statusEl.textContent = "Disconnected";
    statusEl.className = "badge failed";
  };

  eventSource.onmessage = (e) => {
    try {
      const envelope = JSON.parse(e.data);
      appendTimelineEvent(envelope);
      if (envelope.eventType === "CapabilityInvocationStarted" || envelope.eventType === "CapabilityInvocationCompleted") {
        updateExecutionChecklist(envelope);
      }
    } catch (err) {
      console.error("Failed to parse SSE event:", err);
    }
  };
}

// ---------------------------------------------------------------------
// Phase 4 — Approval Execution Checklist
// ---------------------------------------------------------------------

function updateExecutionChecklist(envelope) {
  const container = document.getElementById("executionChecklist");
  if (!container) return;

  const payload = envelope.payload || {};
  const incidentId = envelope.incidentId;
  const steps = payload.executionSteps || [];
  const capability = payload.capability || "Capability";

  const emptyEl = container.querySelector(".empty");
  if (emptyEl) container.innerHTML = "";

  let card = container.querySelector(`[data-incident-id="${incidentId}"]`);
  if (!card) {
    card = document.createElement("div");
    card.className = "checklist-card";
    card.dataset.incidentId = incidentId;
    container.insertBefore(card, container.firstChild);
  }

  if (envelope.eventType === "CapabilityInvocationStarted") {
    const itemsHtml = steps.map((s) => `<div class="checklist-item"><span class="checklist-icon pending">&#9679;</span><span>${s}</span></div>`).join("");
    card.innerHTML = `
      <div class="timeline-header">
        <span class="timeline-stage">${capability}</span>
        <span class="badge stage-running">In Progress</span>
      </div>
      ${itemsHtml}
    `;
  } else {
    const succeeded = payload.status === "succeeded";
    const icon = succeeded ? "&#10003;" : "&#10007;";
    const iconClass = succeeded ? "done" : "failed-icon";
    const badgeHtml = succeeded ? '<span class="badge stage-completed">Completed</span>' : '<span class="badge failed">Failed</span>';
    const itemsHtml = steps.map((s) => `<div class="checklist-item"><span class="checklist-icon ${iconClass}">${icon}</span><span>${s}</span></div>`).join("");
    card.innerHTML = `
      <div class="timeline-header">
        <span class="timeline-stage">${capability}</span>
        ${badgeHtml}
      </div>
      ${itemsHtml}
    `;
  }
}

function appendTimelineEvent(envelope) {
  const container = document.getElementById("agentTimeline");
  if (!container) return;

  const eventType = envelope.eventType;
  const payload = envelope.payload || {};
  const stageName = payload.stage_name || payload.stageName || "Pipeline Stage";

  let titleText = "";
  let badgeHtml = "";
  let detailText = "";

  if (eventType === "StageRequested") {
    titleText = `${stageName} (Stage Requested)`;
    badgeHtml = '<span class="badge stage-running">Running</span>';
    detailText = `Incident: ${envelope.incidentId}`;
  } else if (eventType === "AgentCompleted") {
    const agentId = payload.agent_id || payload.agentId || "Specialist Agent";
    const execMs = payload.execution_time_ms ?? payload.executionTimeMs ?? 0;
    const conf = payload.confidence !== undefined ? (payload.confidence * 100).toFixed(0) + "% confidence" : "";
    titleText = `${stageName} ✓`;
    badgeHtml = '<span class="badge stage-completed">Completed</span>';
    detailText = `Agent: ${agentId} · ${execMs}ms · ${conf} · Incident: ${envelope.incidentId}`;
  } else {
    titleText = `${eventType}`;
    badgeHtml = '<span class="badge">Event</span>';
    detailText = `Incident: ${envelope.incidentId}`;
  }

  const emptyEl = container.querySelector(".empty");
  if (emptyEl) {
    container.innerHTML = "";
  }

  const row = document.createElement("div");
  row.className = "timeline-item";
  row.innerHTML = `
    <div class="timeline-header">
      <span class="timeline-stage">${titleText}</span>
      ${badgeHtml}
    </div>
    <div class="timeline-detail">${detailText}</div>
  `;

  container.insertBefore(row, container.firstChild);
}

// ---------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------

function refreshAll() {
  refreshDigitalTwinLines();
  refreshApprovals();
  refreshIncidents();
  refreshKpis();
  refreshRecommendations();
  refreshRisk();
  refreshPromotionCandidates();
}


document.addEventListener("DOMContentLoaded", () => {
  const tokenInput = document.getElementById("tokenInput");
  tokenInput.value = getToken();
  tokenInput.addEventListener("change", () => {
    setToken(tokenInput.value);
    refreshAll();
    initEventStream();
  });

  document.getElementById("startIncidentForm").addEventListener("submit", startIncident);
  document.getElementById("copilotForm").addEventListener("submit", askCopilot);
  document.getElementById("memorySearchForm").addEventListener("submit", searchDecisionMemory);
  document.getElementById("runRecalibrationBtn").addEventListener("click", runRecalibration);
  document.getElementById("runRagDemoBtn").addEventListener("click", runRagDemo);

  refreshAll();
  initEventStream();
  setInterval(refreshAll, 4000);
});

