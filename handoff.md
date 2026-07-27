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
2. **Enterprise Asset Model (EAM)** (`knowledge/asset_model.py`): Established ground truth hierarchy (`Plant > Factory > Line > Machine > PLC > Sensor > Product > Component`), separating operational physical topology from Knowledge Graph reasoning.

---

## 3. Environment & Credentials

- **Environment File**: `/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS/.env`
- **IBM watsonx Orchestrate Configured Parameters**:
  - `WO_INSTANCE`: `https://api.br-sao.watson-orchestrate.cloud.ibm.com/instances/22dd8b0e-e746-40f6-8142-38f5a7c60210`
  - `WO_API_KEY`: see `.env` (not committed — gitignored)
  - Active `orchestrate` CLI environment: `ados-prod`

---

## 4. How to Verify & Run the System

### Run Complete Test Suite
```bash
cd "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS"
./.venv/bin/pytest tests/test_asset_model.py tests/test_operational_intelligence.py tests/test_phase4a_integration.py tests/test_itsm_connector.py tests/test_phase4b_integration.py tests/test_phase3b_integration.py tests/test_phase2_integration.py
```
*(Status: 43/43 tests passing in 0.16s)*

### Run Demonstration Scripts
```bash
# Phase 2 Agent Pipeline Demo
./.venv/bin/python scripts/run_demo_pipeline.py

# Phase 3B Executive Intelligence Demo
./.venv/bin/python scripts/run_phase3b_demo.py

# Phase 4B Self-Learning & Autonomy Optimization Demo
./.venv/bin/python scripts/run_phase4b_demo.py
```

### Start Backend API Server
```bash
./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

---

## 5. Directory & File Reference Map

- `contracts/`: Shared schemas (`event_envelope.py`, `capabilities.py`, `incident_record.py`, `decision_memory_query.py`).
- `knowledge/`: `asset_model.py` (EAM ground truth), `knowledge_graph.py` (reasoning), `causal_graph.py`, `digital_twin.py`, `learning_engine.py`, `decision_memory_index.py`.
- `agents/`: `sdk/` (`base.py`, `models.py`, `memory_rag.py`), 8 specialist AI agents.
- `orchestrate/`: `orchestrator.py`, `governance.py`, `priority.py`, `audit_trail.py`.
- `integrations/`: `hub.py`, `connectors/` (`watsonx_itsm.py`, `sap.py`, `marketplace.py`, `servicenow.py`, `console.py`).
- `executive/`: `models.py`, `kpi_engine.py`, `recommendation_engine.py`, `edi.py`, `predictive_risk.py`, `copilot.py`, `autonomy_optimizer.py`, `operational_intelligence.py`.
- `backend/`: `app/main.py`, `routers/` (`incidents.py`, `capabilities.py`, `executive.py`, `memory.py`, `events.py`, `health.py`).
- `adr/`: Architectural Decision Records 0008, 0009, 0010.
