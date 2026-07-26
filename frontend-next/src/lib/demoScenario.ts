// The canned "Simulate Quality Alert" scenario the Mission Control home
// screen triggers. Isolated in its own module (not inlined in the page
// component) so it can be updated independently of any future dataset
// changes without touching component code - see
// knowledge/seed_data.py / documentation/02_Demo_Dataset_and_Digital_Twin.md
// for the source of truth these values must match.

import type { StartIncidentRequest } from "./api";

export const MOTOR_HOUSING_QUALITY_ALERT: StartIncidentRequest = {
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
};
