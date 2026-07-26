"use client";

import { useEffect, useState } from "react";
import { getToken, subscribeToTokenChanges } from "./api";

/**
 * Reactively tracks whether a service token is present, so pages can gate
 * TanStack Query calls with `enabled: hasToken` instead of firing an
 * unauthenticated request (and a noisy 401) on first render before the
 * user has entered one in HeaderTelemetryBar.
 */
export function useHasToken(): boolean {
  const [hasToken, setHasToken] = useState(() => Boolean(getToken()));

  useEffect(() => {
    // Legitimate effect use: subscribing to an external event, calling
    // setState from within the callback - not synchronously in the effect
    // body itself.
    return subscribeToTokenChanges(() => setHasToken(Boolean(getToken())));
  }, []);

  return hasToken;
}
