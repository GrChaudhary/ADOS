# ADOS System Handoff & Session Continuation Guide

This document summarizes the current state, architecture, completed phases, environment setup, and verification instructions for **ADOS (Autonomous Defect & Orchestration System)** to ensure seamless continuation in future sessions.

---

## 1. System Overview & Architecture

ADOS is an autonomous, multi-agent AI system for industrial manufacturing defect detection, root-cause isolation, governance enforcement, self-learning, and executive decision intelligence — for **Nova Motors, Plant 04 (Austin, TX)**, an EV powertrain assembly facility producing the **EV-POW-800V** (800V Electric Drive Unit).

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
- **Causal Graph** (`knowledge/causal_graph.py`): Probabilistic condition-to-outcome graph, now covering all 8 demo incident categories (see Phase 0 below).
- **Digital Twin** (`knowledge/digital_twin.py`): Live factory line state, CNC spindle parameters, and inventory soft locks — now 4 lines (see Phase 1 below).
- **Agent SDK & 8 Agents** (`agents/`): `VisionSpecAgent`, `CausalIsolationAgent`, `CADSpecAgent`, `SubstitutionAgent`, `ParameterAdjustmentAgent`, `ImpactSimulationAgent`, `ReroutingAgent`, `FeedbackCalibrationAgent`.
- **ADR**: [ADR-0008](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/adr/0008-digital-twin-placement.md).

### Phase 3A & 3B: Orchestration, Enterprise Connectors & Executive Intelligence
- **Decision Orchestrator** (`orchestrate/orchestrator.py`): Multistage state machine with preemption and `ApprovalQueue` holding.
- **IBM watsonx Orchestrate ITSM Connector** (`integrations/connectors/watsonx_itsm.py`): Real integration adapter with IBM Cloud IAM authentication for `CreateIncident`, `CreateChangeRequest`, `ScheduleMaintenance`, `NotifyOperator`.
- **SAP ERP Connector** (`integrations/connectors/sap.py`): `CreatePurchaseOrder`, `ReserveInventory`.
- **Executive Intelligence Suite** (`executive/`): KPI Engine, What-If Autonomy Simulation, Strategic Recommendation Engine, Enterprise Decision Intelligence (EDI), Predictive Risk Analytics, Evidence-Grounded Natural Language Copilot.
- **ADR**: [ADR-0009](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/adr/0009-executive-intelligence-module.md).

### Phase 4A & 4B: Self-Learning Engine, Decision Memory & Autonomous Optimization
- **Decision Memory REST API** (`backend/app/routers/memory.py`): `/memory/search`, `/memory/records/{id}`, `/memory/records`.
- **External B2B Marketplace Connector** (`integrations/connectors/marketplace.py`): `QueryExternalStock`, `CreateExternalPO`, `GetFreightQuote`.
- **Self-Learning Engine** (`knowledge/learning_engine.py`): Replays incident audit trails to recalibrate Causal Graph edge weights via Bayesian & EMA updates.
- **Memory-Augmented Agent RAG** (`agents/sdk/memory_rag.py`): Precedent retrieval attaching `[PRECEDENT]` evidence and boosting agent decision confidence.
- **Executive Autonomy Policy Optimizer** (`executive/autonomy_optimizer.py`): Recommends promoting low-risk decision categories to Tier 0 autonomy based on operator acceptance and confidence.
- **ADR**: [ADR-0010](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/adr/0010-learning-engine-and-autonomy-optimization.md).

### Phase 0 — Demo Dataset & Phases 1–4 of the Demo Blueprint (SSE, Recommendation Comparison, Execution Checklist)
Built incrementally, several in parallel with Antigravity as a second builder:
- **Phase 0 (dataset)**: originally a "Nova Motors Detroit Plant" dataset; **superseded by the Plant 04 Austin TX rename** — see §6.
- **Phase 1 (multi-line digital twin)**: `knowledge/digital_twin.py` and `knowledge/asset_model.py` extended from one line to four (`Line 1`, `Line 2`, `Line 3`, `Warehouse`); `GET /digital-twin/lines`. Built by Antigravity from [PHASE1_ANTIGRAVITY_HANDOFF.md](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/docs/PHASE1_ANTIGRAVITY_HANDOFF.md), reviewed and two bugs fixed (router reading a disconnected store copy instead of the orchestrator's live one; wrong active-product SKU on one line).
- **Phase 2 (live agent timeline / SSE)**: `backend/app/routers/events_stream.py` — `GET /events/stream` with query-param token auth (browser `EventSource` can't set headers) since the router-level bearer-header auth on `events.py` would otherwise 401 every connection. Built by Antigravity from [PHASE2_ANTIGRAVITY_HANDOFF.md](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/docs/PHASE2_ANTIGRAVITY_HANDOFF.md), reviewed and fixed (test fixture missing lifespan context, subscriber-queue leak on disconnect, frontend reading the wrong JSON key casing).
- **Phase 3 (Option A/B/C recommendation comparison)**: `executive/recommendation_comparison.py` (`RecommendationComparisonEngine`) ranks each incident's recorded alternatives into starred options with cost/downtime/risk/savings; `GET /executive/incidents/{id}/options`. `orchestrate/orchestrator.py` now persists the Impact Simulation Agent's `ranked_options` onto `IncidentRecord.alternatives` (previously computed but discarded).
- **Phase 4 (approval execution checklist)**: orchestrator now publishes `CapabilityInvocationStarted`/`CapabilityInvocationCompleted` events around the execution stage (previously silent), reusing Phase 2's event bus — no new route needed.
- **Phase 5A (narrative demo page, plain JS)**: `frontend/demo.html`/`demo.js`/`demo.css` — a full Mission Control + tabbed Incident Workspace, SSE-driven, verified end-to-end with headless Playwright. **Superseded by the React/Next.js rebuild (§6)** but kept in place, untouched, as a working reference/porting source — not deleted.

---

## 3. Architectural Refactoring Milestones
1. **Executive vs. Operational Intelligence Split**: Divided `/executive` endpoints into **Enterprise Intelligence** (`/executive/enterprise`) for C-suite business metrics and **Operational Intelligence** (`/executive/operational`) for plant managers (agent failures, queue depth, workflow latency, connector health, inventory locks).
2. **Enterprise Asset Model (EAM)** (`knowledge/asset_model.py`): Ground truth hierarchy (`Plant > Factory > Line > Machine > PLC > Sensor > Product > Component`), separating operational physical topology from Knowledge Graph reasoning. `KnowledgeGraph.resolveAssetLineage()` delegates to it. Still single-plant (`PLANT-04-AUSTIN > FAC-P04`, 4 lines) — no multi-plant data yet.

---

## 4. Phase 5 Pivot — dataset rename, governance rewrite, React/Next.js rebuild

Mid-session, six "Head of Product" documentation files appeared in `documentation/` (a parallel planning effort, not authored as part of the phases above) describing a materially larger product vision than what had been built: a different demo dataset, a "Deep Space Industrial" design system, 7 major UI screens, and a governance model using flat dollar thresholds. The user confirmed these are now canon, not aspirational, and greenlit:

1. **Dataset rename** (`knowledge/seed_data.py`, `executive/seed_data.py`, `executive/incident_generator.py`, `knowledge/causal_graph.py`, `knowledge/digital_twin.py`, `knowledge/asset_model.py`, agent defaults, scripts, tests): Nova Motors **Detroit** → **Plant 04, Austin TX**. Single BOM product **EV-POW-800V** (800V Electric Drive Unit) with 5 real components — Motor Housing (`MH-8820`), Rotor Shaft (`RS-4401`), Ceramic Bearing (`CB-1099`), Stator Core (`SC-3310`), Cooling Plate (`CP-7700`) — replacing the old "5 separate products" model. Suppliers: Titan Metals Inc. (incumbent, `SUP-301`), PrecisionCast GmbH (preferred alt, `SUP-302`), Rapid Components (`SUP-303`), ForgeWorks Ltd (`SUP-304`), SKF Industrial (`SUP-305`) — `SteelCore` dropped, supplier roles swapped vs. the old scheme. Lines: `Line 1` (Stator & Rotor Cell), `Line 2` (Housing Machining & Inspection — CNC-101/CNC-102/ROB-401/CMM-02, now the `DEGRADED`/incident line instead of `Line 3`), `Line 3` (Final Drive Testing & Pack Out), `Warehouse` (Central Warehouse ASRS). Tolerance tightened to ±0.020mm (was ±0.05mm) — updated `vision_spec_agent.py`'s hardcoded defect thresholds to match, since they weren't spec-driven. Incident generator re-weighted (via weighted sampling, not round-robin) to approximate `documentation/02`'s documented 100-record category breakdown.
2. **Governance rewrite** (`orchestrate/governance.py`): `assign_policy_tier(capability, confidence, estimated_cost_usd)` now follows the documented dollar-threshold matrix — `<$25k` & `>90%` confidence → Tier 0; the `$25k–$250k` medium band **never** reaches Tier 0 (the doc's own row targets Tier 1); `>$250k` or a "critical" capability (mapped to the existing `"high"` risk class) → Tier 2 regardless of confidence. Replaces the old risk-class-first + per-class confidence threshold model. This is an intentional behavior change — a new test (`test_governance_medium_cost_band_never_reaches_tier0`) proves the one case where old and new models diverge.
3. **`/api/v1` alias routes + CORS** (`backend/app/main.py`, `backend/app/config.py`): every router re-mounted a second time under `/api/v1` (same router objects, zero logic duplication) so the new frontend can call the documented `/api/v1/...` paths while all existing tests keep hitting the unprefixed paths unchanged. `CORSMiddleware` added (`frontend_dev_origin` setting, default `http://localhost:3000`) since the Next.js dev server runs cross-origin, unlike `frontend/`'s same-origin static mount.
4. **React/Next.js rebuild** (`frontend-next/`, sibling to `frontend/` — nothing in `frontend/` was touched or disturbed): Next.js 16 (App Router) + TypeScript + Tailwind v4 (CSS-native `@theme` config — this version has **no `tailwind.config.ts`**, a real breaking change from older Next.js/Tailwind conventions) + TanStack Query + Zustand.
   - `src/app/globals.css`: the full `documentation/03_Design_System.md` "Deep Space Industrial" palette as CSS custom properties, wired into Tailwind's `@theme inline` block.
   - `src/lib/api.ts`: API client typed **literally per the wire casing of every endpoint** (verified against the actual router/model source — the real backend's JSON casing is genuinely inconsistent field-by-field, not just per-endpoint; a normalization layer would hide real behavior for no gain across ~17 endpoints).
   - `src/components/design-system/`: shared `AppShell`/`Sidebar`/`HeaderTelemetryBar`/`FooterStatusBar` (wraps every route via `layout.tsx`), `KpiCard`/`StatusPulse`/`OptionCard`/`PlaceholderScreen`.
   - **2 screens built** (mine): `src/app/digital-twin/page.tsx` (Mission Control) and `src/app/incidents/[incidentId]/page.tsx` (Incident Workspace, 6 tabs) — ported directly from `frontend/demo.js`'s verified logic, including the SSE-opened-before-backfill-with-dedupe pattern (`event_bus.stream()` has no replay) and the "disable Simulate Alert for an incident's whole lifetime" guard (an unapproved incident permanently holds its line's preemption lock).
   - **5 placeholder routes** (Antigravity's, in progress): `executive/enterprise`, `agents/network`, `memory`, `governance`, `integrations` — see [PHASE5B_ANTIGRAVITY_HANDOFF.md](file:///Users/gauravchaudhary/Documents/Projects/Ai%20Projects/Hackathon/ADOS/docs/PHASE5B_ANTIGRAVITY_HANDOFF.md).
   - `npm run build`/`npm run lint` clean; verified end-to-end with headless Playwright against the real running Next.js + FastAPI pair.

**Explicitly deferred** (not built by either side yet): 3D CAD heatmap viewer (Three.js), deep Agent Swarm Network graph visualization, Policy Studio no-code editor, multi-tenant admin, Decision Replay compliance suite — the remaining "10 product module" enterprise-suite items from `documentation/06_Product_Execution_Master_Plan.md`.

---

## 5. Environment & Credentials

- **Backend env file**: `/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS/.env` (see `.env.example` for the full key list — IBM watsonx Orchestrate instance/API key, event bus backend, service auth token. **Do not paste actual secret values into this or any other checked-in doc** — reference the file, not its contents).
- Default `service_auth_token` for local dev: `dev-local-only-token` (used by both frontends and the demo/test scripts).
- **Frontend-next env file**: `frontend-next/.env.local` (gitignored) — `NEXT_PUBLIC_ADOS_BACKEND_ORIGIN` / `ADOS_BACKEND_ORIGIN`, both default to `http://localhost:8000`.
- Node v26+ / npm 11+ required for `frontend-next/` (no pnpm/yarn installed in this environment).

---

## 6. How to Verify & Run the System

### Run Complete Test Suite
```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS"
./.venv/bin/pytest tests/ backend/tests/ -q
```
*(Status: 92/92 tests passing.)*

### Run Demonstration Scripts
```bash
# Phase 2 Agent Pipeline Demo
./.venv/bin/python scripts/run_demo_pipeline.py

# Phase 3A Orchestrator Demo (full incident lifecycle incl. execution checklist)
./.venv/bin/python scripts/run_orchestrator_demo.py

# Phase 3B Executive Intelligence Demo
./.venv/bin/python scripts/run_phase3b_demo.py

# Phase 4B Self-Learning & Autonomy Optimization Demo
./.venv/bin/python scripts/run_phase4b_demo.py

# Phase 3 Recommendation Comparison Demo (Option A/B/C)
./.venv/bin/python scripts/run_phase3_options_demo.py
```

### Start the Backend API Server
```bash
./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```
Every route is served both unprefixed and under `/api/v1/...` (e.g. `/executive/kpis` and `/api/v1/executive/kpis` return identical data). Stop with `lsof -ti:8000 -sTCP:LISTEN | xargs -r kill`.

### Option A — Old Ops Dashboard (plain HTML/JS, no build step)
Open **http://localhost:8000/dashboard/** and enter the service token (`dev-local-only-token`) in the top-right field. This is the original debug/ops dashboard (Phases 1-4's panels) plus `frontend/demo.html` (Phase 5A's narrative page, still reachable at `/dashboard/demo.html`) — both still fully working, untouched by the Phase 5 pivot.

### Option B — New React/Next.js App (the live rebuild)
```bash
cd frontend-next
npm run dev
```
Open **http://localhost:3000/digital-twin** and enter the service token in the header. Requires the backend running on `:8000` (CORS + the `/api/v1` alias are already configured for this). 2 of 7 screens are real (Mission Control, Incident Workspace); the other 5 are placeholders pending Antigravity's Phase 5B work.

---

## 7. Directory & File Reference Map

- `contracts/`: Shared schemas (`event_envelope.py`, `capabilities.py`, `incident_record.py`, `decision_memory_query.py`, `agent_events.py`).
- `knowledge/`: `asset_model.py` (EAM ground truth), `knowledge_graph.py` (reasoning), `causal_graph.py`, `digital_twin.py`, `learning_engine.py`, `decision_memory_index.py`, `seed_data.py` (Nova Motors Plant 04 dataset).
- `agents/`: `sdk/` (`base.py`, `models.py`, `memory_rag.py`), 8 specialist AI agents.
- `orchestrate/`: `orchestrator.py`, `governance.py` (dollar-threshold tier matrix), `priority.py`, `audit_trail.py`, `preemption.py`.
- `integrations/`: `hub.py`, `connectors/` (`watsonx_itsm.py`, `sap.py`, `marketplace.py`, `servicenow.py`, `console.py`).
- `executive/`: `models.py`, `kpi_engine.py`, `recommendation_engine.py`, `recommendation_comparison.py` (Option A/B/C), `edi.py`, `predictive_risk.py`, `copilot.py`, `autonomy_optimizer.py`, `operational_intelligence.py`, `seed_data.py`, `incident_generator.py`.
- `backend/`: `app/main.py` (router registration + `/api/v1` aliasing + CORS), `app/config.py`, `app/routers/` (`incidents.py`, `capabilities.py`, `executive.py`, `memory.py`, `learning.py`, `events.py`, `events_stream.py`, `digital_twin.py`, `health.py`).
- `frontend/`: `index.html`/`app.js`/`styles.css` (original ops dashboard) + `demo.html`/`demo.js`/`demo.css` (Phase 5A narrative page) — plain HTML/JS, no build step, both superseded-but-untouched by the Next.js rebuild.
- `frontend-next/`: the live React/Next.js rebuild — `src/app/` (routes), `src/components/design-system/` (shared shell + reusable pieces), `src/lib/` (`api.ts` client, `agents.ts`, `store.ts`, `demoScenario.ts`, `useHasToken.ts`).
- `documentation/`: the "Head of Product" spec set now driving Phase 5 — `01_Product_Design_Specification.md` (7 screens), `02_Demo_Dataset_and_Digital_Twin.md` (the dataset, now implemented), `03_Design_System.md` (tokens, implemented), `04_Demo_UI_Architecture.md` (frontend architecture), `05_Product_Bible.md` (system + governance reference, governance now implemented), `06_Product_Execution_Master_Plan.md` (long-term roadmap — most of it explicitly deferred, see §4).
- `docs/`: ADR-numbered design docs (`000`-`011`), this file, and 3 Antigravity handoff prompts (`PHASE1_ANTIGRAVITY_HANDOFF.md`, `PHASE2_ANTIGRAVITY_HANDOFF.md`, `PHASE5B_ANTIGRAVITY_HANDOFF.md`).
- `adr/`: Architectural Decision Records 0001-0010.
- `Blueprints/`: `ADOS_Enterprise_Architecture_Blueprint.md`, `ADOS_Demo_Product_Experience_Blueprint.md` (the original hackathon demo narrative spec — superseded by `documentation/`'s more detailed spec set, but still a useful quick narrative reference).

---

## 8. Current Status & Next Steps

**In progress**: Antigravity is building the 5 remaining Phase 5B screens (Executive Command Center, Agent Swarm Network, Decision Memory Hub, Governance Autonomy Admin, Integration Monitor) in `frontend-next/`, per `docs/PHASE5B_ANTIGRAVITY_HANDOFF.md`. Each has a working placeholder route today.

**When picking this up next**:
1. Check whether Antigravity's Phase 5B work has landed (`git log --oneline` in `frontend-next/`'s commits) — review it the same way Phases 1/2 were reviewed in this session (real bugs were found and fixed both times: a disconnected store, a leaking subscriber, a wrong status line; a missing lifespan context, a resource leak, a wrong JSON key).
2. Full test suite (`./.venv/bin/pytest tests/ backend/tests/ -q`) plus `cd frontend-next && npm run build && npm run lint` should both stay clean.
3. Explicitly deferred scope (§4) is a legitimate place to continue if the 7-screen rebuild is otherwise complete — but confirm with the user before starting any of it; none of it has been scoped or greenlit yet.
