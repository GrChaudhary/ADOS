// Session-local state that must survive client-side navigation between
// /digital-twin and /incidents/[id] (Next.js App Router unmounts the
// previous route's page component on navigation, so plain useState would
// reset - Zustand's store lives outside the React tree).
//
// Tracks: incidents started from this browser session, and which lines
// currently have one in flight. The backend's DigitalTwinStore does flip a
// line's real status on incident start/resolve (orchestrate/orchestrator.py's
// run_incident/_finalize), but that only lands on the next 5s poll of
// /digital-twin/lines - this overlay exists purely to show the line as
// DEGRADED instantly, in the gap between clicking "Simulate Quality Alert"
// and the next poll, not to compensate for a backend that never updates it.

import { create } from "zustand";

export interface RecentIncident {
  incidentId: string;
  lineId: string;
  status: "in_progress" | string; // "in_progress" | "Resolved" | "Failed"
}

interface MissionControlState {
  recentIncidents: RecentIncident[];
  activeIncidentLines: Set<string>;
  addIncident: (incidentId: string, lineId: string) => void;
  setIncidentStatus: (incidentId: string, status: string) => void;
}

export const useMissionControlStore = create<MissionControlState>((set) => ({
  recentIncidents: [],
  activeIncidentLines: new Set(),
  addIncident: (incidentId, lineId) =>
    set((state) => ({
      recentIncidents: [...state.recentIncidents, { incidentId, lineId, status: "in_progress" }],
      activeIncidentLines: new Set(state.activeIncidentLines).add(lineId),
    })),
  setIncidentStatus: (incidentId, status) =>
    set((state) => {
      const record = state.recentIncidents.find((i) => i.incidentId === incidentId);
      const nextActiveLines = new Set(state.activeIncidentLines);
      if (record && status !== "in_progress") {
        nextActiveLines.delete(record.lineId);
      }
      return {
        recentIncidents: state.recentIncidents.map((i) => (i.incidentId === incidentId ? { ...i, status } : i)),
        activeIncidentLines: nextActiveLines,
      };
    }),
}));
