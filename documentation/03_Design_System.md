# Design System Specification
**Platform**: ADOS (Autonomous Defect & Orchestration System)  
**Document Version**: 1.0  
**Status**: Approved for Implementation  
**Author**: Head of Product  

---

## 1. Visual Identity: "Deep Space Industrial"

The ADOS Design System is engineered to transform complex factory telemetry and multi-agent reasoning into a sleek, high-precision Mission Control interface.

### Core Visual Attributes
- **Theme**: Dark Mode Native (reduces eye strain for 24/7 plant control rooms).
- **Surface Depth**: Glassmorphism with dark semi-transparent backdrops (`rgba(17, 24, 39, 0.75)`) and subtle backdrop blur (`12px`).
- **High Information Density**: Compact spacing, crisp typography, and high contrast accents.

---

## 2. Color Palette & UI Tokens

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  COLOR PALETTE                                                              │
│  [ Dark Base ]   #0B0F19 (Deep Void)   #111827 (Surface Glass)               │
│  [ Accents ]     #10B981 (Emerald)     #EF4444 (Red)     #3B82F6 (Cobalt)    │
│                  #F59E0B (Amber)       #8B5CF6 (Purple)  #64748B (Slate Text)│
└─────────────────────────────────────────────────────────────────────────────┘
```

### Color Token Reference Table

| Token Name | Hex Code | Purpose / Usage |
| :--- | :--- | :--- |
| `--bg-app` | `#0B0F19` | Main application background (Deep Void) |
| `--bg-card` | `#111827` | Card and modal container background |
| `--bg-glass` | `rgba(17, 24, 39, 0.75)` | Floating drawers and glassmorphic panels |
| `--border-subtle` | `rgba(255, 255, 255, 0.08)` | Standard card borders |
| `--border-accent` | `rgba(59, 130, 246, 0.30)` | Active container borders |
| `--status-emerald`| `#10B981` | Healthy line, high confidence (>90%), approved execution |
| `--status-red` | `#EF4444` | Line stopped, critical defect, emergency override active |
| `--status-cobalt` | `#3B82F6` | Primary action buttons, active navigation link |
| `--status-amber` | `#F59E0B` | Warning alert, holding queue, medium confidence |
| `--status-purple`| `#8B5CF6` | Autonomous Tier 0 action, AI Swarm activity |
| `--text-primary` | `#F9FAFB` | Primary headings and high-priority metrics |
| `--text-secondary`| `#9CA3AF` | Labels, subtitles, and secondary descriptions |
| `--text-mono` | `#38BDF8` | Part numbers, timestamps, coordinates, and telemetry |

---

## 3. Typography Scale

ADOS uses a dual-font pairing: **Inter** for clean UI navigation and **JetBrains Mono** for machine telemetry, code snippets, and part identifiers.

```css
/* Typography Design Tokens */
:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* Font Sizes & Line Heights */
  --text-h1: 32px / 40px;      /* Main Dashboard Title */
  --text-h2: 24px / 32px;      /* Section Headers */
  --text-h3: 18px / 26px;      /* Card Titles & Modal Headers */
  --text-body: 14px / 20px;    /* Standard Content & Form Fields */
  --text-caption: 12px / 16px; /* Subtitles, Labels & Tooltips */
  --text-mono-sm: 12px / 16px; /* Telemetry Data, Part IDs, Timestamps */
}
```

---

## 4. Iconography & AI Specialist Agent Avatars

Each of the 8 AI Specialist Agents has a designated color badge, SVG icon, and visual avatar token:

| Agent Name | Icon Symbol | Color Accent | Avatar Badge Design |
| :--- | :--- | :--- | :--- |
| `VisionSpecAgent` | 👁️ Optical Lens | `#10B981` (Emerald) | Circle icon with green pulse outer ring |
| `CADSpecAgent` | 📐 Blueprint Draft | `#3B82F6` (Cobalt) | Square grid icon with blue vector lines |
| `CausalIsolationAgent`| 🧠 Neural Tree | `#8B5CF6` (Purple) | Glowing node tree icon |
| `SubstitutionAgent` | 📦 Inventory Box | `#F59E0B` (Amber) | Box swap arrows icon |
| `ParameterAdjustmentAgent`| ⚙️ CNC Gear | `#06B6D4` (Cyan) | Spinning gear wheel icon |
| `ImpactSimulationAgent`| 📈 Financial Trend| `#EC4899` (Pink) | Bar chart forecast overlay |
| `ReroutingAgent` | 🚚 Logistics Truck| `#14B8A6` (Teal) | Route line with location pin |
| `FeedbackCalibrationAgent`| 🔄 Recalibrate Loop| `#6366F1` (Indigo) | Circular sync arrows icon |

---

## 5. Reusable Component Specifications

### 1. Stat KPI Card (Glassmorphic Metric Tile)
```html
<div class="ados-card-kpi">
  <div class="kpi-label">Revenue Protected</div>
  <div class="kpi-value text-emerald">$4,280,000</div>
  <div class="kpi-trend trend-up">+14.2% MoM vs target</div>
</div>
```

```css
.ados-card-kpi {
  background: var(--bg-glass);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}
```

### 2. Multi-Option Recommendation Card
Components display Option A, B, and C side-by-side with star ratings, risk indicators, financial savings badges, and direct 1-click execution triggers.

```
┌────────────────────────────────────────────────────────┐
│ OPTION A (Recommended) ⭐⭐⭐⭐⭐                      │
│ Switch Supplier to PrecisionCast GmbH + Recalibrate    │
├────────────────────────────────────────────────────────┤
│ Savings: $430,000  | Delay: 8 Hours  | Confidence: 94%│
├────────────────────────────────────────────────────────┤
│ [ APPROVE OPTION A ]                                   │
└────────────────────────────────────────────────────────┘
```

### 3. Autonomy Threshold Slider Control
Interactive slider allowing executives to dynamically tune Tier 0 autonomous execution limits.

```
Tier 0 Risk Cap: [$ 50,000 ] ══════════════●════════ [$ 250,000]
Current Setting: $50,000 | 78.4% Autonomous Execution Ratio
```

---

## 6. CSS Animations & Keyframes

```css
/* Status Pulse Animations */
@keyframes pulse-emerald {
  0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
  70% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
  100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

@keyframes pulse-red {
  0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.8); }
  70% { box-shadow: 0 0 0 12px rgba(239, 68, 68, 0); }
  100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}

.status-active-green {
  animation: pulse-emerald 2s infinite;
}

.status-incident-red {
  animation: pulse-red 1.5s infinite;
}
```
