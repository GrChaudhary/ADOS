# Demo UI Specification & Enterprise Front-End Architecture
**Platform**: ADOS (Autonomous Defect & Orchestration System)  
**Document Version**: 1.0  
**Status**: Approved for Implementation  
**Author**: Head of Product  

---

## 1. Front-End Architecture Overview

To ensure ADOS feels like a tier-1 Enterprise SaaS platform (comparable to Palantir Foundry, Datadog, or Snowflake), the front-end architecture is built on a high-performance modular layout structure.

### Tech Stack Standards
- **Framework**: React 18 / Next.js 14 / Vite TypeScript
- **State Management**: Zustand (local UI state) + TanStack React Query v5 (REST data fetching & caching)
- **Real-Time Data**: Server-Sent Events (`EventSource` connecting to backend `/api/v1/events/stream`)
- **Styling**: Vanilla CSS Modules with custom properties (`03_Design_System.md`)
- **Charts & Visualization**: Recharts / Chart.js + Three.js / Canvas for CAD Step overlays

---

## 2. Global Layout Architecture (App Shell)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TOP TELEMETRY HEADER                                                        │
│ [⚡ ADOS] [Plant 04 - Bangalore, Karnataka]  [Incidents: 1 🔴] [SSE: Live 🟢]  [Copilot 💬]│
├──────────────┬──────────────────────────────────────────────────────────────┤
│ SIDEBAR NAV  │ MAIN CONTENT CANVAS                                          │
│              │                                                              │
│ 📊 Executive │                                                              │
│ 🏭 Twin Room │                                                              │
│ 🚨 Incident  │                                                              │
│ 🧠 Agents    │                                                              │
│ 💾 Memory    │                                                              │
│ 🛡️ Autonomy  │                                                              │
│ 🔌 Hub       │                                                              │
│              │                                                              │
├──────────────┴──────────────────────────────────────────────────────────────┤
│ FOOTER STATUS BAR                                                           │
│ [Agent Swarm: 8 Active] [watsonx ITSM: Connected 🟢] [SAP ERP: Connected 🟢] │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Hierarchy Tree

```
<AppShell>
  ├── <HeaderTelemetryBar>
  │     ├── <FacilitySelector />
  │     ├── <ActiveIncidentBadge />
  │     ├── <SSEConnectionIndicator />
  │     └── <UserProfileMenu />
  ├── <SidebarNavigation />
  ├── <MainContentArea>
  │     ├── <ExecutiveDashboardView />
  │     ├── <DigitalTwinControlRoomView />
  │     ├── <ActiveIncidentWorkspaceView />
  │     │     ├── <VisionCadSplitViewer />
  │     │     ├── <CausalReasoningTree />
  │     │     ├── <ImpactSimulationOptions />
  │     │     └── <OrchestrationTimeline />
  │     └── <GovernancePolicyView />
  ├── <CopilotSideDrawer /> (Triggered via Cmd+K)
  └── <FooterStatusBar />
</AppShell>
```

---

## 3. Screen Layout Wireframes (ASCII Specifications)

### Screen 3 Wireframe: Live Incident Workspace (`/incidents/{id}`)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🚨 INCIDENT-2026-8840 | Line 2 - Motor Housing Bore Tolerance Exceeded      │
├─────────────────────────────────────────────────────────────────────────────┤
│ STEP 1: VISION & CAD DIAGNOSIS       │ STEP 2: CAUSAL ROOT CAUSE ISOLATION  │
│ ┌──────────────────────────────────┐ │ ┌──────────────────────────────────┐ │
│ │ [Image Heatmap View]             │ │ │ Tooling Wear (68%)               │ │
│ │ Scan offset: +0.031 mm           │ │ │   ├── Spindle CNC-102 Wear       │ │
│ │ Spec limit:  0.020 mm            │ │ │ Humidity Spike (28%)             │ │
│ │ Spec variance: +0.011 mm         │ │ │   └── Ambient Humidity 78%       │ │
│ └──────────────────────────────────┘ │ └──────────────────────────────────┘ │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ STEP 3: RESOLUTION RECOMMENDATIONS (Impact Simulation)                      │
│ ┌─────────────────────────┬─────────────────────────┬─────────────────────┐ │
│ │ OPTION A ⭐⭐⭐⭐⭐       │ OPTION B                │ OPTION C            │ │
│ │ Switch to PrecisionCast │ Wait for Primary Stock  │ Recalibrate Speed   │ │
│ │ Savings: $430,000       │ Downtime: 5 Days        │ High Scrap Risk     │ │
│ │ Delay: 8 Hours          │ Loss: $2,100,000        │ Loss: $150,000      │ │
│ │ [ APPROVE OPTION A ]    │ [ SELECT OPTION B ]     │ [ SELECT OPTION C ] │ │
│ └─────────────────────────┴─────────────────────────┴─────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ STEP 4: REAL-TIME SYSTEM ORCHESTRATION AUDIT TIMELINE                        │
│ 09:41:00 VisionSpecAgent completed visual bounding box                      │
│ 09:41:30 ImpactSimulationAgent evaluated 3 options                          │
│ 09:42:18 watsonx_itsm: ServiceNow Ticket INC-90422 Created [STATUS: 🟢 OK]  │
│ 09:42:20 SAP Connector: Purchase Order PO-88301 Issued    [STATUS: 🟢 OK]  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. API & SSE Data Binding Mappings

| UI Component | Data Source Type | API / SSE Endpoint | Update Frequency |
| :--- | :--- | :--- | :--- |
| `HeaderTelemetryBar` | SSE Stream | `/api/v1/events/stream` | Real-time push |
| `ExecutiveKPiCards` | REST GET | `/api/v1/executive/enterprise/kpis` | 30 seconds poll |
| `AutonomySimulator` | REST POST | `/api/v1/executive/enterprise/simulate` | On slider change |
| `DigitalTwinLines` | REST GET | `/api/v1/digital-twin/status` | 5 seconds poll |
| `IncidentEvidence` | REST GET | `/api/v1/incidents/{id}/evidence` | On mount |
| `PrecedentSearch` | REST POST | `/api/v1/memory/search` | Debounced 300ms |
| `ApprovalTrigger` | REST POST | `/api/v1/orchestrator/approve` | On button click |

---

## 5. Enterprise SaaS Polish Guidelines

To elevate ADOS from a hackathon demo to an Enterprise SaaS product:

1. **Zero Layout Shifts**: Skeleton loaders and exact pixel height containers for all chart and timeline panels.
2. **Instant Micro-Feedback**: Button clicks trigger immediate loading state indicators (<50ms) while awaiting backend response.
3. **Toast System**: System events (e.g., *"ServiceNow Ticket INC-90422 created successfully"*) display non-intrusive toast notifications in the top right corner.
4. **Keyboard Accessibility**: Global shortcut `Command+K` opens the Evidence Copilot drawer from anywhere in the application.
5. **Clear Autonomy Badges**: Always display clear visual tags demarcating whether an action was executed **Tier 0 (Autonomous)**, **Tier 1 (Approved)**, or **Tier 2 (Override)**.
