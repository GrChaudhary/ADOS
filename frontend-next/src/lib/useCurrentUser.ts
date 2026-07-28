"use client";

import { useSyncExternalStore } from "react";
import { AuthUser, getStoredUser, subscribeToTokenChanges } from "./api";

/**
 * Reactively tracks the logged-in user (backend/app/rbac.py's User,
 * cached in localStorage by api.login()) - replaces
 * frontend-next/src/lib/usePersona.ts's fully client-side, unauthenticated
 * "pick who you are" switcher. Same useSyncExternalStore pattern as
 * useHasToken() (and reuses its token-changed event, since login/logout
 * always touch both the token and the user together).
 */
export function useCurrentUser(): AuthUser | null {
  return useSyncExternalStore(subscribeToTokenChanges, getStoredUser, () => null);
}
