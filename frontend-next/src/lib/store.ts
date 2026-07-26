// Session-local state that must survive client-side navigation between
// /digital-twin and /incidents/[id] (Next.js App Router unmounts the
// previous route's page component on navigation, so plain useState would
// reset - Zustand's store lives outside the React tree).
//
// Tracks: incidents started from this browser session, and which lines
// currently have one in flight. The real DigitalTwinStore doesn't yet
// flip a line's status on incident start/resolve (see
// docs/PHASE5B_ANTIGRAVITY_HANDOFF.md's note on this), so this overlay is
// an honest, session-local "this line has an active incident" signal,
// not a claim about what the backend's digital twin itself reports.

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
