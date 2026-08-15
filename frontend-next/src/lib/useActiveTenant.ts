"use client";

import { useSyncExternalStore } from "react";
import { getActiveTenantId, subscribeToTenantChanges } from "./api";

/**
 * Reactively tracks the active tenant (see api.ts's getActiveTenantId for
 * the selection rule) so components — the tenant indicator in
 * HeaderTelemetryBar, any future tenant-scoped query — re-render on login,
 * logout, or an explicit switch, the same useSyncExternalStore pattern
 * useHasToken/useCurrentUser already use for the same reason (same-tab
 * localStorage writes don't fire the native `storage` event).
 */
export function useActiveTenantId(): string | null {
  return useSyncExternalStore(subscribeToTenantChanges, getActiveTenantId, () => null);
}
