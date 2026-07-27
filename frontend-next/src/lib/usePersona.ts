"use client";

import { useSyncExternalStore } from "react";

/**
 * Active user persona (RBAC session) - single source of truth. Any page
 * that needs to know "who is acting" (approver identity on approve
 * actions, approval-limit enforcement) reads it from here instead of
 * hardcoding a name, so the /admin persona switcher actually has an
 * effect elsewhere in the app.
 */
export interface Persona {
  id: string;
  name: string;
  role: string;
  avatar: string;
  accessLevel: string;
  defaultView: string;
  approvalLimitUsd: number;
}

export const PERSONAS: Persona[] = [
  {
    id: "emma",
    name: "Emma Vance",
    role: "Quality & Reliability Engineer",
    avatar: "👩‍🔬",
    accessLevel: "Tier 1 Approval Authority",
    defaultView: "Active Incident Workspace",
    approvalLimitUsd: 250000,
  },
  {
    id: "marcus",
    name: "Marcus Vance",
    role: "Plant Operations Manager",
    avatar: "👨‍💼",
    accessLevel: "Tier 1 & Preemption Override",
    defaultView: "Operational Control Room",
    approvalLimitUsd: 500000,
  },
  {
    id: "sophia",
    name: "Sophia Vance",
    role: "VP of Manufacturing & Supply Chain",
    avatar: "👩‍💼",
    accessLevel: "Tier 2 Executive Dual Signature",
    defaultView: "Executive Intelligence Command Center",
    approvalLimitUsd: 5000000,
  },
  {
    id: "auditor",
    name: "Compliance Auditor",
    role: "Regulatory Audit & Safety Compliance",
    avatar: "📑",
    accessLevel: "Read-Only Compliance Replay",
    defaultView: "Decision Replay Studio",
    approvalLimitUsd: 0,
  },
];

const DEFAULT_PERSONA_ID = "emma";
const PERSONA_STORAGE_KEY = "ados_active_persona";
const PERSONA_CHANGED_EVENT = "ados-persona-changed";

export function getActivePersonaId(): string {
  if (typeof window === "undefined") return DEFAULT_PERSONA_ID;
  return window.localStorage.getItem(PERSONA_STORAGE_KEY) || DEFAULT_PERSONA_ID;
}

export function setActivePersonaId(id: string): void {
  window.localStorage.setItem(PERSONA_STORAGE_KEY, id);
  // Same-tab localStorage writes don't fire the native `storage` event - dispatch
  // our own so useActivePersona() (this same tab) re-reads it, mirroring
  // useHasToken's ados-token-changed pattern.
  window.dispatchEvent(new Event(PERSONA_CHANGED_EVENT));
}

function subscribeToPersonaChanges(callback: () => void): () => void {
  window.addEventListener(PERSONA_CHANGED_EVENT, callback);
  return () => window.removeEventListener(PERSONA_CHANGED_EVENT, callback);
}

/**
 * useSyncExternalStore (not useState+useEffect) so the server snapshot can
 * stay fixed at the default persona while the client snapshot reads the
 * real localStorage value - avoids a hydration mismatch for a returning
 * user who previously selected a non-default persona, same reasoning as
 * useHasToken.
 */
export function useActivePersona(): Persona {
  const id = useSyncExternalStore(subscribeToPersonaChanges, getActivePersonaId, () => DEFAULT_PERSONA_ID);
  return PERSONAS.find((p) => p.id === id) ?? PERSONAS[0];
}
