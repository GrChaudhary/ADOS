# ADOS System Handoff & Session Continuation Guide

This document summarizes the current state, architecture, completed phases, environment setup, and verification instructions for **ADOS (Autonomous Defect & Orchestration System)** to ensure seamless continuation in future sessions.

---

## 1. System Overview & Architecture

ADOS is an autonomous, multi-agent AI system for industrial manufacturing defect detection, root-cause isolation, governance enforcement, self-learning, and executive decision intelligence.

```
                                  USER / EXECUTIVE / OPERATOR
                                               │
                        ┌──────────────────────┴──────────────────────┐
                        ▼                                             ▼
          L6: Enterprise Intelligence                      L6: Operational Intelligence
     (Revenue, MTTR, Supplier Risk, Copilot)          (Agent Failures, Queue Depth, Latency, Locks)
                        │                                             │
                        └──────────────────────┬──────────────────────┘
                                               ▼
                                    L5: Governance Policy Engine
                              (Tier 0 Autonomous / Tier 1 / Tier 2)
                                               │
                        ┌──────────────────────┴──────────────────────┐
                        ▼                                             ▼
          L4: Decision Orchestrator                      L4: Integration Hub
      (State Machine & Approval Queue)            (WXO ITSM, SAP, Marketplace, Console)
                        │                                             │
                        └──────────────────────┬──────────────────────┘
                                               ▼
                                  L3: Decision Memory & Learning
                           (/memory/search API, Causal Recalibration)
                                               │
                        ┌──────────────────────┴──────────────────────┐
                        ▼                                             ▼
             L2: 8 Specialist AI Agents                   L2: Operational Ground Truth
          (Vision, Causal, CAD, Sub, etc.)            (Enterprise Asset Model: Plant->Sensor)
                                               │
                                               ▼
                                    L1: Event Bus & Envelope
```

---

## 2. Completed Phases & Key Deliverables

### Phase 1: Core Foundation & Contracts
- FastAPI backend router structure (`backend/app/routers/`).
- Standard `EventEnvelope`, `CapabilityCall`, `CapabilityResponse`, and `GovernanceInfo` contracts (`contracts/`).
- Redis & In-Memory Event Bus abstraction (`backend/app/eventbus/`).

### Phase 2: Knowledge Graph, Causal Graph, Digital Twin, & Agent SDK
- **Knowledge Graph** (`knowledge/knowledge_graph.py`): Typed query surface for parts, products, specifications, and substitutions.
- **Causal Graph** (`knowledge/causal_graph.py`): Probabilistic condition-to-outcome graph (`COND-TOL-DRIFT`, `COND-HUMIDITY-SPIKE`) with calibration hooks.
- **Digital Twin** (`knowledge/digital_twin.py`): Live factory line state, CNC spindle parameters, and inventory soft locks.
- **Agent SDK & 8 Agents** (`agents/`): `VisionSpecAgent`, `CausalIsolationAgent`, `CADSpecAgent`, `SubstitutionAgent`, `ParameterAdjustmentAgent`, `ImpactSimulationAgent`, `ReroutingAgent`, `FeedbackCalibrationAgent`.
- **ADR**: [ADR-0008](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/adr/0008-digital-twin-placement.md).

### Phase 3A & 3B: Orchestration, Enterprise Connectors & Executive Intelligence
- **Decision Orchestrator** (`orchestrate/orchestrator.py`): Multistage state machine with preemption and `ApprovalQueue` holding.
- **IBM watsonx Orchestrate ITSM Connector** (`integrations/connectors/watsonx_itsm.py`): Real integration adapter with IBM Cloud IAM authentication for `CreateIncident`, `CreateChangeRequest`, `ScheduleMaintenance`, `NotifyOperator`.
- **SAP ERP Connector** (`integrations/connectors/sap.py`): `CreatePurchaseOrder`, `ReserveInventory`.
- **Executive Intelligence Suite** (`executive/`): KPI Engine, What-If Autonomy Simulation (fixed MTTR & cost delta bug), Strategic Recommendation Engine, Enterprise Decision Intelligence (EDI), Predictive Risk Analytics, Evidence-Grounded Natural Language Copilot.
- **ADR**: [ADR-0009](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/adr/0009-executive-intelligence-module.md).

### Phase 4A & 4B: Self-Learning Engine, Decision Memory & Autonomous Optimization
- **Decision Memory REST API** (`backend/app/routers/memory.py`): `/memory/search`, `/memory/records/{id}`, `/memory/records`.
- **External B2B Marketplace Connector** (`integrations/connectors/marketplace.py`): `QueryExternalStock`, `CreateExternalPO`, `GetFreightQuote`.
- **Self-Learning Engine** (`knowledge/learning_engine.py`): Replays incident audit trails to recalibrate Causal Graph edge weights via Bayesian & EMA updates.
- **Memory-Augmented Agent RAG** (`agents/sdk/memory_rag.py`): Precedent retrieval attaching `[PRECEDENT]` evidence and boosting agent decision confidence.
- **Executive Autonomy Policy Optimizer** (`executive/autonomy_optimizer.py`): Recommends promoting low-risk decision categories to Tier 0 autonomy based on operator acceptance and confidence.
- **ADR**: [ADR-0010](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/adr/0010-learning-engine-and-autonomy-optimization.md).

### Architectural Refactoring Milestones
1. **Executive vs. Operational Intelligence Split**: Divided `/executive` endpoints into **Enterprise Intelligence** (`/executive/enterprise`) for C-suite business metrics and **Operational Intelligence** (`/executive/operational`) for plant managers (agent failures, queue depth, workflow latency, connector health, inventory locks).
2. **Enterprise Asset Model (EAM)** (`knowledge/asset_model.py`): Established ground truth hierarchy (`Plant > Factory > Line > Machine > PLC > Sensor > Product > Component`), separating operational physical topology from Knowledge Graph reasoning. `KnowledgeGraph.resolveAssetLineage()` delegates to it. Still single-line seeded (`PLANT-NA-01 > FAC-P1 > Line 3`) — no multi-plant/multi-line data yet.

### Phase 4 Dashboard Surfacing (previously CLI-only, now live)
Phase 4B's Learning Engine, Memory RAG, and Autonomy Optimizer were fully implemented and tested but only reachable via `scripts/run_phase4b_demo.py` — invisible in the running app. Fixed:
- **New router** `backend/app/routers/learning.py`: `GET /learning/recalibration` (causal graph recalibration log), `GET /learning/promotion-candidates` (Tier 0 eligibility), `POST /learning/memory-rag-demo` (memory-boosted agent reasoning) — all read-only, backed by Decision Memory's seed-based precedent store (same pattern as `memory.py`'s singleton index).
- **Security fix**: `backend/app/routers/memory.py` was the only router missing `Depends(require_service_auth)` — every sibling router (executive, incidents, events, capabilities) has it. Added it, and updated the 3 pre-existing `/memory/*` tests in `tests/test_phase4a_integration.py` to send a bearer token (they were passing only because the endpoint was unintentionally open).
- **Frontend** (`frontend/index.html`, `app.js`, `styles.css`): new "Phase 4 — Decision Memory & Self-Learning" section with 4 live panels — Decision Memory Search, Causal Graph Recalibration, Memory-Augmented Agent Reasoning demo, Autonomy Tier 0 Promotion Candidates. Verified end-to-end with a headless Playwright pass against the real running server (not just curl).

---

## 3. Environment & Credentials

- **Environment File**: `/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS/.env`
- **IBM watsonx Orchestrate Configured Parameters**:
  - `WO_INSTANCE`: `https://api.br-sao.watson-orchestrate.cloud.ibm.com/instances/22dd8b0e-e746-40f6-8142-38f5a7c60210`
  - `WO_API_KEY`: `p0jNi4161XhcDwhEfO1WrOpU2fy-Mqj1b9kEAII_RADd`
  - Active `orchestrate` CLI environment: `ados-prod`

---

## 4. How to Verify & Run the System

### Run Complete Test Suite
```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS"
./.venv/bin/pytest tests/
```
*(Status: 68/68 tests passing in 0.16s — full `tests/` dir, includes asset model, operational intelligence, all phases, connectors, and the memory router auth fix.)*

### Run Demonstration Scripts
```bash
# Phase 2 Agent Pipeline Demo
./.venv/bin/python scripts/run_demo_pipeline.py

# Phase 3B Executive Intelligence Demo
./.venv/bin/python scripts/run_phase3b_demo.py

# Phase 4B Self-Learning & Autonomy Optimization Demo
./.venv/bin/python scripts/run_phase4b_demo.py
```

### Start Backend API Server & View the Dashboard
```bash
./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```
Then open **http://localhost:8000/dashboard/** and enter the service token
`dev-local-only-token` in the top-right field (saved to localStorage). The
Phase 4 panels are below the main approvals/KPI section. Stop the server with
`lsof -ti:8000 -sTCP:LISTEN | xargs -r kill`.

---

## 5. Directory & File Reference Map

- `contracts/`: Shared schemas (`event_envelope.py`, `capabilities.py`, `incident_record.py`, `decision_memory_query.py`).
- `knowledge/`: `asset_model.py` (EAM ground truth), `knowledge_graph.py` (reasoning), `causal_graph.py`, `digital_twin.py`, `learning_engine.py`, `decision_memory_index.py`.
- `agents/`: `sdk/` (`base.py`, `models.py`, `memory_rag.py`), 8 specialist AI agents.
- `orchestrate/`: `orchestrator.py`, `governance.py`, `priority.py`, `audit_trail.py`.
- `integrations/`: `hub.py`, `connectors/` (`watsonx_itsm.py`, `sap.py`, `marketplace.py`, `servicenow.py`, `console.py`).
- `executive/`: `models.py`, `kpi_engine.py`, `recommendation_engine.py`, `edi.py`, `predictive_risk.py`, `copilot.py`, `autonomy_optimizer.py`, `operational_intelligence.py`.
- `backend/`: `app/main.py`, `routers/` (`incidents.py`, `capabilities.py`, `executive.py`, `memory.py`, `learning.py`, `events.py`, `health.py`).
- `frontend/`: `index.html`, `app.js`, `styles.css` — plain HTML/JS ops dashboard served at `/dashboard/`, no build step. Auth via `dev-local-only-token`.
- `adr/`: Architectural Decision Records 0008, 0009, 0010.
- `Blueprints/`: `ADOS_Enterprise_Architecture_Blueprint.md` (Phase 1-4 roadmap, now complete), `ADOS_Demo_Product_Experience_Blueprint.md` (hackathon demo narrative spec — see §6, not yet built).

---

## 6. Demo Experience Blueprint — Gap Analysis & Planned Next Phases

`Blueprints/ADOS_Demo_Product_Experience_Blueprint.md` describes a narrative,
judge-facing demo ("Emma, a Quality Engineer at Nova Motors") — a "Mission
Control" home screen, live agent timeline, Option A/B/C recommendation
comparison, animated approval checklist, digital twin widget, and an
"IBM Workflow View". **This is not built yet.** The current `frontend/` is a
functional debug/ops dashboard (verified working, see §2's "Phase 4 Dashboard
Surfacing"), not the narrative experience the blueprint describes.

**Status as of this handoff: plan proposed to user, no phase greenlit yet.**
Start a future session by asking the user which phase to begin.

### Gap summary (audited against actual code, not assumed)
1. **Dataset**: `executive/seed_data.py` has only 5 incidents; `knowledge/seed_data.py` uses generic placeholder names (`FAC-P1`, `P-1002`, `S-201`/`S-202`). Zero "Nova Motors" branding or the blueprint's named products/machines/suppliers exist anywhere in the repo.
2. **Live agent timeline**: the data model already supports it — `orchestrate/agent_runner.py` publishes per-stage `AgentCompleted` events, `EventBus.stream()` exists in `backend/app/eventbus/`. But `backend/app/routers/events.py` only exposes polling (`GET /events`), no SSE/WebSocket transport.
3. **Option A/B/C recommendation comparison**: `executive/recommendation_engine.py` only produces flat, independent cross-incident recommendations — no per-incident ranked-alternatives-with-tradeoffs logic exists. Needs new logic, likely synthesized from the substitution/parameter-adjustment/simulation agents' existing per-incident outputs.
4. **Digital twin widget**: `knowledge/digital_twin.py` and the newer `knowledge/asset_model.py` both only seed one line (`Line 3`). No multi-line data, no route exposing raw line status.
5. **Frontend narrative shell**: no summary KPI strip, no tabbed Incident Workspace (Overview/Evidence/Reasoning/Recommendations/Execution/Audit), no star-rated comparison screen, no approval progress checklist, no "IBM Workflow View". Would be a new page, not an edit to the existing dashboard.

### Recommended phase plan (dependency order)
- **Phase 0 — Demo dataset (Nova Motors)** [M]: rewrite `knowledge/seed_data.py` + `executive/seed_data.py` with real branding, 5 products/machines/suppliers, a generator script for ~100 incidents across the 8 categories the blueprint lists. Blocks everything else looking real.
- **Phase 1 — Digital twin, multi-line** [S/M]: seed Line 1/2/3(+Warehouse) in `digital_twin.py`, add `GET /digital-twin/lines`, simple colored status strip.
- **Phase 2 — Live agent timeline (SSE)** [M]: new SSE route off `EventBus.stream()`, frontend timeline consumer.
- **Phase 3 — Option A/B/C recommendation comparison** [L]: new module producing 2-3 ranked options per incident with delay/savings/confidence; needs investigation of existing agent outputs before final sizing.
- **Phase 4 — Approval execution checklist** [S/M]: reuses Phase 2's SSE plumbing on the execution/capability-invoke stage.
- **Phase 5 — Demo Mode frontend (the narrative itself)** [XL]: home screen, incident popup, tabbed Incident Workspace, Executive Mode view, IBM Workflow View, copy pass (Observe→Understand→Decide→Coordinate→Learn). Depends on Phases 0-4 for real data. **Design decision made**: build this as a new page (e.g. `frontend/demo.html`) alongside the existing verified ops dashboard, not a rewrite of it — lower risk, and matches the blueprint's own "reveal the architecture only after the story" instruction (ops dashboard = the reveal).
