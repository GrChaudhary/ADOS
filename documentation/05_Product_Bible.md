# Product Bible: Living Source of Truth
**Platform**: ADOS (Autonomous Defect & Orchestration System)  
**Document Version**: 1.0  
**Status**: Authoritative Reference  
**Author**: Head of Product  

---

## 1. Vision & Core Mission Statement

> **"When a factory doesn't know what to do next, ADOS does."**

ADOS is an autonomous, multi-agent AI operating system for industrial manufacturing. It connects physical factory line sensor data, automated visual inspections, CAD specifications, enterprise resource planning (SAP), IT service management (IBM watsonx Orchestrate ITSM), and external supplier networks to resolve production defects in minutes instead of days.

---

## 2. 6-Layer Platform System Architecture

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

### Layer Breakdown
- **Layer 1: Event Bus & Standard Envelope**: Unified messaging bus (`backend/app/eventbus/`) passing typed `EventEnvelope` payloads across all services.
- **Layer 2: Specialist AI Agents & Ground Truth**: 8 domain-specific AI agents operating on top of the Enterprise Asset Model (`knowledge/asset_model.py`).
- **Layer 3: Decision Memory & Learning Engine**: Vector database precedent search (`/memory/search`) and Bayesian Causal Graph edge weight recalibration (`knowledge/learning_engine.py`).
- **Layer 4: Decision Orchestrator & Integration Hub**: Multistage workflow state machine managing approval holding queues and external connectors (`watsonx_itsm`, `sap`, `marketplace`).
- **Layer 5: Governance Policy Engine**: Strict autonomy rule evaluator enforcing Tier 0 (Autonomous), Tier 1 (Human Approval), and Tier 2 (Multi-Executive Override).
- **Layer 6: Executive & Operational Intelligence Suite**: Dual intelligence endpoints serving business P&L leaders (`/executive/enterprise`) and plant operations engineers (`/executive/operational`).

---

## 3. The 8 AI Specialist Agents Reference Manual

```
┌───────────────────────────┬───────────────────────────┬───────────────────────────┐
│ 👁️ VisionSpecAgent        │ 📐 CADSpecAgent           │ 🧠 CausalIsolationAgent   │
│ Optical defect isolation  │ STEP file CAD alignment   │ Bayesian root cause tree  │
├───────────────────────────┼───────────────────────────┼───────────────────────────┤
│ 📦 SubstitutionAgent      │ ⚙️ ParameterAdjustmentAg. │ 📈 ImpactSimulationAgent  │
│ Alt supplier matching     │ CNC feed rate tuning      │ What-If financial impact  │
├───────────────────────────┼───────────────────────────┼───────────────────────────┤
│ 🚚 ReroutingAgent         │ 🔄 FeedbackCalibrationAg. │                           │
│ Freight & logistics route │ Self-learning graph update│                           │
└───────────────────────────┴───────────────────────────┴───────────────────────────┘
```

1. **`VisionSpecAgent`**: Processes camera optical images; isolates defect regions and computes bounding box coordinates.
2. **`CADSpecAgent`**: Aligns defect scan against STEP 3D CAD models (`.step`), outputting micro-meter offset vectors.
3. **`CausalIsolationAgent`**: Evaluates Causal Graph probabilistic edges, isolating tooling wear, environmental spikes, or raw material defects.
4. **`SubstitutionAgent`**: Scans internal inventory & external B2B marketplaces to identify compatible component replacements.
5. **`ParameterAdjustmentAgent`**: Calculates machine feed, speed, and spindle parameter adjustments to compensate for minor defects without stopping the line.
6. **`ImpactSimulationAgent`**: Runs Monte Carlo simulations comparing resolution pathways across cost, lead time, downtime, and quality risk.
7. **`ReroutingAgent`**: Evaluates logistics routes and freight options for urgent replacement component delivery.
8. **`FeedbackCalibrationAgent`**: Replays completed incident audit trails to update Causal Graph edge weights via Bayesian inference.

---

## 4. Enterprise Integration Architecture Matrix

| Target System | Connector File | Auth / Protocol | Capability Calls | Business Value |
| :--- | :--- | :--- | :--- | :--- |
| **IBM watsonx Orchestrate** | `integrations/connectors/watsonx_itsm.py` | IBM IAM OAuth 2.0 REST | `CreateIncident`, `CreateChangeRequest`, `NotifyOperator` | IT/OT incident compliance & ticketing |
| **SAP S/4HANA ERP** | `integrations/connectors/sap.py` | BAPI / OData REST | `CreatePurchaseOrder`, `ReserveInventory` | Auto-procurement of alternative components |
| **External B2B Market** | `integrations/connectors/marketplace.py` | REST API | `QueryExternalStock`, `GetFreightQuote` | Real-time global supplier stock search |
| **Factory MES / PLC** | `knowledge/digital_twin.py` | OPC-UA / Modbus | `UpdateMachineFeed`, `ApplySoftLock` | Direct physical machine parameter tuning |

---

## 5. Governance Autonomy Tier Matrix

```
Risk Level    Financial Exposure    Confidence    Governance Tier    Execution Path
───────────────────────────────────────────────────────────────────────────────────
Low           < $25,000            > 90%         Tier 0             Fully Autonomous (Auto-Dispatch)
Medium        $25,000 – $250,000   > 80%         Tier 1             1-Click Engineer Approval
High          > $250,000           Any           Tier 2             Multi-Executive Dual Signature
Critical      Process Modification Any           Tier 2             VP Ops + Safety Approval
```

---

## 6. Self-Learning & Precedent RAG Architecture

1. **Precedent Retrieval**: Before an agent makes a decision, `MemoryRAG` searches historical records for incidents with similar part IDs and failure modes.
2. **Confidence Boosting**: When high-confidence precedents are found, agent decision confidence increases by up to +15%, helping promote low-risk decisions to Tier 0 autonomy.
3. **Bayesian Graph Calibration**: Post-incident execution, `FeedbackCalibrationAgent` updates Causal Graph weights:
   $$W_{\text{new}} = W_{\text{old}} + \alpha \cdot (\text{ActualOutcome} - W_{\text{old}})$$

---

## 7. Platform Roadmap

```
  COMPLETED PHASES                              FUTURE ROADMAP
┌──────────────────────────────────────────┐  ┌──────────────────────────────────────────┐
│ ✅ Phase 1: Core Event Bus & Contracts   │  │ 🚀 Phase 5: Multi-Plant Federated        │
│ ✅ Phase 2: Knowledge Graph & Twin       │  │             Learning & Supplier Network  │
│ ✅ Phase 3: Decision Orchestrator & ITSM │  │ 🚀 Phase 6: Generative Autonomous        │
│ ✅ Phase 4: Self-Learning Engine & RAG   │  │             Line Re-Scheduling Engine  │
└──────────────────────────────────────────┘  └──────────────────────────────────────────┘
```

---

## 8. Master Glossary of Terms

- **AOI**: Automated Optical Inspection camera cell.
- **BOM**: Bill of Materials.
- **CAD**: Computer-Aided Design (STEP 3D file format).
- **CMM**: Coordinate Measurement Machine.
- **EAM**: Enterprise Asset Model (hierarchy of physical plant components).
- **MTTR**: Mean Time to Recovery (average time to resolve a production line failure).
- **OEE**: Overall Equipment Effectiveness (percent of planned manufacturing time that is productive).
- **Precedent RAG**: Retrieval-Augmented Generation using past incident memory records.
- **Tier 0 Autonomy**: Zero-human-intervention automated decision execution.
- **watsonx Orchestrate**: IBM's agentic workflow automation platform.
