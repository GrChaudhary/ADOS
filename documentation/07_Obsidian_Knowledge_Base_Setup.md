# Obsidian Knowledge Base & Development Integration Guide
**Platform**: ADOS (Autonomous Defect & Orchestration System)  
**Document Version**: 1.0  
**Status**: Active Integration Specification  
**Author**: Head of Product / Technical Lead  

---

## 1. Overview & Setup

Since all ADOS documentation (`documentation/`, `docs/`, `adr/`, `Blueprints/`) is written in standard Markdown, you can open the entire `ADOS/` directory directly as an **Obsidian Vault**.

### Quick Setup Steps
1. Open **Obsidian**.
2. Click **"Open folder as vault"**.
3. Select the repository root:  
   `/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS`
4. Enable **Wiki-links** in Obsidian Settings: `Settings > Files & links > Use [[Wikilinks]]`.

---

## 2. Core Development Workflows with Obsidian

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ADOS OBSIDIAN KNOWLEDGE GRAPH                                               │
│                                                                             │
│  [[06_Product_Execution_Master_Plan]] ──► [[05_Product_Bible]]              │
│                 │                                  │                        │
│                 ▼                                  ▼                        │
│     [[01_Product_Design_Spec]] ──────────► [[ADR-0010_Learning_Engine]]    │
│                 │                                  │                        │
│                 ▼                                  ▼                        │
│     [[03_Design_System]] ────────────────► [[VisionSpecAgent]]             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1. Interactive Graph View for Multi-Agent & Architecture Mapping
- **Feature**: Press `Cmd + G` in Obsidian to view the interactive **Graph View**.
- **Value**: See real-time visual connections between:
  - Product Specifications (`[[01_Product_Design_Specification]]`)
  - AI Agents (`[[VisionSpecAgent]]`, `[[CausalIsolationAgent]]`)
  - Architecture Decisions (`[[ADR-0008]]`, `[[ADR-0009]]`, `[[ADR-0010]]`)
  - API Contracts (`[[010-api-contracts]]`)

---

### 2. Obsidian Canvas for Visual Agent Workflows (`.canvas`)
Obsidian Canvas lets you create infinite visual whiteboards with live markdown cards, code snippets, images, and connection arrows.

- **Suggested Canvases to Create in `documentation/canvases/`**:
  - `Incident_Resolution_Flow.canvas`: Step-by-step visual diagram connecting sensor trigger ➔ Vision scan ➔ CAD offset ➔ Causal root cause ➔ 1-click approval ➔ watsonx/SAP PO dispatch.
  - `Agent_Swarm_Architecture.canvas`: Visual hierarchy of all 8 AI Specialist Agents and the Decision Orchestrator.

---

### 3. Dynamic Feature & Sprint Tracking (Dataview Plugin)
By adding simple YAML frontmatter to markdown notes, you can turn Obsidian into a live project management tracker using the popular **Dataview** plugin.

#### Example Note Frontmatter (`documentation/features/01_incident_replay.md`):
```yaml
---
type: feature
sprint: 1
owner: Emma
status: in_progress
agent_dependencies: [VisionSpecAgent, CausalIsolationAgent]
---
```

#### Dataview Live Query (in any note):
```dataview
TABLE status, owner, agent_dependencies
FROM "documentation"
WHERE type = "feature" AND sprint = 1
SORT status ASC
```

---

### 4. Code & Spec Cross-Referencing
You can link directly from product notes to Python source files in Obsidian:

```markdown
- Implement memory precedent retrieval in [[agents/sdk/memory_rag.py]]
- Verify watsonx ITSM OAuth token handling in [[integrations/connectors/watsonx_itsm.py]]
```

---

### 5. Recommended Obsidian Community Plugins for ADOS

| Plugin Name | Purpose | Benefit for ADOS |
| :--- | :--- | :--- |
| **Dataview** | Dynamic SQL-like queries | Track sprints, agent statuses, and open tasks dynamically |
| **Excalidraw** | Embedded whiteboard drawing | Sketch UI wireframes, CAD vector diagrams, and line maps |
| **Mermaid preview** | Live diagram generation | Render sequence diagrams and flowcharts natively |
| **Omnisearch** | Deep AI / OCR text search | Instant search across all markdown, code, and PDF blueprints |
| **Advanced Tables** | Format Markdown tables | Effortlessly format KPI tables, BOM lists, and API contracts |

---

## 3. Recommended Folder Structure in Obsidian

```
ADOS/ (Vault Root)
├── .obsidian/                  # Obsidian configuration settings
├── documentation/               # Enterprise Product Suite
│   ├── 01_Product_Design_Specification.md
│   ├── 02_Demo_Dataset_and_Digital_Twin.md
│   ├── 03_Design_System.md
│   ├── 04_Demo_UI_Architecture.md
│   ├── 05_Product_Bible.md
│   ├── 06_Product_Execution_Master_Plan.md
│   ├── 07_Obsidian_Knowledge_Base_Setup.md
│   └── canvases/               # Obsidian .canvas visual diagrams
│       ├── agent_swarm.canvas
│       └── incident_flow.canvas
├── adr/                        # Architecture Decision Records (0001 - 0010)
├── docs/                       # Core Technical Documentation
└── Blueprints/                  # Experience & Architecture Blueprints
```
