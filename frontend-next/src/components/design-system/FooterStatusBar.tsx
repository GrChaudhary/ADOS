"use client";

// documentation/04_Demo_UI_Architecture.md section 2 - FooterStatusBar.
// Connector labels are read from the same /integrations/status query the
// Integration Monitor (/integrations) uses - shares its TanStack Query
// cache (same queryKey), so this doesn't add an extra request. "8
// specialist agents" is a fixed architectural fact (docs/003-agent-
// architecture.md's 8 roles), not a live count, so it isn't phrased as
// "Active".

import { useQuery } from "@tanstack/react-query";
import { api, IntegrationConnectorItem } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

function connectorLabel(item: IntegrationConnectorItem | undefined, fallbackName: string): string {
  if (!item) return `${fallbackName}: —`;
  return `${fallbackName}: ${item.status}`;
}

export function FooterStatusBar() {
  const hasToken = useHasToken();
  const statusQuery = useQuery<IntegrationConnectorItem[]>({
    queryKey: ["integrations-status"],
    queryFn: api.getIntegrationsStatus,
    enabled: hasToken,
  });
  const byId = new Map((statusQuery.data ?? []).map((s) => [s.id, s]));

  return (
    <footer className="flex items-center gap-6 border-t border-border-subtle bg-card px-6 py-2 text-xs text-text-secondary">
      <span>8 Specialist Agents</span>
      <span>{connectorLabel(byId.get("watsonx_itsm"), "watsonx ITSM")}</span>
      <span>{connectorLabel(byId.get("sap"), "SAP ERP")}</span>
      <span>{connectorLabel(byId.get("local_llm"), "Local LLM")}</span>
    </footer>
  );
}
