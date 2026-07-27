"use client";

import { useSyncExternalStore } from "react";
import { getToken, subscribeToTokenChanges } from "./api";

/**
 * Reactively tracks whether a service token is present, so pages can gate
 * TanStack Query calls with `enabled: hasToken` instead of firing an
 * unauthenticated request (and a noisy 401) on first render before the
 * user has entered one in HeaderTelemetryBar.
 *
 * useSyncExternalStore (rather than useState+useEffect) so the server
 * snapshot can be forced to `false` (matching SSR, which has no
 * `window`/localStorage) while the client snapshot reads the real value -
 * without that split, a returning user with a token already saved would
 * hit a React hydration mismatch on first paint.
 */
export function useHasToken(): boolean {
  return useSyncExternalStore(
    subscribeToTokenChanges,
    () => Boolean(getToken()),
    () => false
  );
}
