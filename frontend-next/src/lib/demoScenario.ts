// The canned "Simulate Quality Alert" scenarios the Mission Control home
// screen can trigger, one per digital-twin line. Isolated in its own module
// (not inlined in the page component) so it can be updated independently of
// any future dataset changes without touching component code - see
// knowledge/seed_data.py / documentation/02_Demo_Dataset_and_Digital_Twin.md
// for the source of truth these values must match.
//
// All four scenarios pass a `measured_bore_diameter_mm` reading outside the
// 44.980-45.020mm tolerance band because that's the one field
// agents/vision_spec_agent.py actually reads to trigger a defect - it isn't
// part/line-aware. The part_number/label per scenario is thematically
// matched to its line for the demo narrative, but the resulting evidence
// text will still read in bore-measurement language regardless of line.

import type { StartIncidentRequest } from "./api";

export interface QualityAlertScenario {
  lineId: string;
  label: string;
  request: StartIncidentRequest;
}

export const QUALITY_ALERT_SCENARIOS: QualityAlertScenario[] = [
  {
    lineId: "Line 1",
    label: "Line 1 — Rotor Shaft runout (RS-4401)",
    request: {
      plant_id: "FAC-P04-L1",
      line_id: "Line 1",
      part_number: "RS-4401",
      vision_data: { measured_bore_diameter_mm: 45.028 },
      priority: {
        safety_impact: 0.6,
        customer_impact: 0.7,
        line_down_cost_per_hour_usd: 8_500 * 60,
        production_priority: 0.7,
        is_systemic: false,
      },
    },
  },
  {
    lineId: "Line 2",
    label: "Line 2 — Motor Housing bore (MH-8820)",
    request: {
      plant_id: "FAC-P04-L2",
      line_id: "Line 2",
      part_number: "MH-8820",
      vision_data: { measured_bore_diameter_mm: 45.031 },
      priority: {
        safety_impact: 0.7,
        customer_impact: 0.8,
        line_down_cost_per_hour_usd: 8_500 * 60, // documentation/02: $8,500/minute downtime cost
        production_priority: 0.75,
        is_systemic: false,
      },
    },
  },
  {
    lineId: "Line 3",
    label: "Line 3 — Ceramic Bearing OD (CB-1099)",
    request: {
      plant_id: "FAC-P04-L3",
      line_id: "Line 3",
      part_number: "CB-1099",
      vision_data: { measured_bore_diameter_mm: 44.965 },
      priority: {
        safety_impact: 0.65,
        customer_impact: 0.75,
        line_down_cost_per_hour_usd: 8_500 * 60,
        production_priority: 0.7,
        is_systemic: false,
      },
    },
  },
  {
    lineId: "Warehouse",
    label: "Warehouse — Outbound staging re-check (CP-7700)",
    request: {
      plant_id: "FAC-P04-WH",
      line_id: "Warehouse",
      part_number: "CP-7700",
      vision_data: { measured_bore_diameter_mm: 45.045 },
      priority: {
        safety_impact: 0.4,
        customer_impact: 0.6,
        line_down_cost_per_hour_usd: 8_500 * 60,
        production_priority: 0.5,
        is_systemic: false,
      },
    },
  },
];
