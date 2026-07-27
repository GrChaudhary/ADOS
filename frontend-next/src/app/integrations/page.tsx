"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { api, IntegrationConnectorItem } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

function badgeClass(c: IntegrationConnectorItem): string {
  // Checked before `connected` - marketplace.py's execute() never makes a
  // real HTTP call, so it reports connected=true (it "responds") even
  // though it isn't reaching a real system. Simulated must never render
  // with the same green as a genuinely live connection like Cloudant's.
  if (/simulated/i.test(c.status)) return "bg-amber/20 text-amber border-amber/40";
  if (c.connected) return "bg-emerald/20 text-emerald border-emerald/40";
  return "bg-status-red/20 text-status-red border-status-red/40";
}

export default function IntegrationsPage() {
  const hasToken = useHasToken();

  const statusQuery = useQuery<IntegrationConnectorItem[]>({
    queryKey: ["integrations-status"],
    queryFn: api.getIntegrationsStatus,
    refetchInterval: 5000,
    enabled: hasToken,
  });

  const watsonxTest = useMutation({
    mutationFn: api.testWatsonxConnection,
  });

  const connectors = statusQuery.data ?? [];
  const connectedCount = connectors.filter((c) => c.connected).length;

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Enterprise Integration Monitor</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald/10 text-emerald border border-emerald/30">
              Layer 4 Integration Hub
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Real-time enterprise connectors, live Cloudant NoSQL document stores, ping latency metrics, and capability contracts.
          </p>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono">
          <div className="px-3 py-1.5 rounded-lg bg-glass border border-border-subtle text-text-secondary">
            Connectors Active:{" "}
            <span className="text-emerald font-bold">
              {hasToken && statusQuery.data ? `${connectedCount} / ${connectors.length}` : "—"}
            </span>
          </div>
        </div>
      </div>

      {!hasToken && (
        <p className="text-sm text-status-red">Enter a service token above to load connector status.</p>
      )}
      {hasToken && statusQuery.isLoading && (
        <p className="text-sm text-text-secondary">Polling live connector health &amp; Cloudant status...</p>
      )}
      {hasToken && statusQuery.isError && (
        <p className="text-sm text-status-red">Could not load connector status (check backend &amp; service token).</p>
      )}

      {/* Connector Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {connectors.map((c) => {
          const isCloudant = c.id === "cloudant_nosql";
          return (
            <div
              key={c.id}
              className={`p-6 rounded-xl bg-card/60 backdrop-blur-md border ${
                isCloudant ? "border-emerald/40 shadow-emerald/5 shadow-xl" : "border-border-subtle hover:border-border-accent"
              } transition-all space-y-4 shadow-lg`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">{isCloudant ? "☁️" : "🔌"}</span>
                  <h2 className="text-base font-semibold text-text-primary">{c.name}</h2>
                </div>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono border font-semibold ${badgeClass(c)}`}>
                  {c.status}
                </span>
              </div>

              <p className="text-xs text-text-secondary">{c.description}</p>

              <div className="p-3 rounded-lg bg-glass border border-border-subtle space-y-2 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-text-secondary">Auth Protocol:</span>
                  <span className="text-cobalt font-medium">{c.auth}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">Module Source:</span>
                  <span className="text-mono text-text-primary">{c.module}</span>
                </div>
                {c.latency_ms !== undefined && (
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Ping Latency:</span>
                    <span className="text-emerald font-bold">{c.latency_ms} ms</span>
                  </div>
                )}
                {c.doc_count !== undefined && (
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Live Cloudant Doc Count:</span>
                    <span className="text-purple font-bold">{c.doc_count} Documents</span>
                  </div>
                )}
                {c.host && (
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Host Instance:</span>
                    <span className="text-xs text-text-primary truncate max-w-[200px]">{c.host}</span>
                  </div>
                )}
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-mono text-text-secondary">Exposed Capabilities:</div>
                <div className="flex flex-wrap gap-1.5">
                  {c.capabilities.map((cap) => (
                    <span key={cap} className="px-2 py-1 rounded text-[11px] font-mono bg-cobalt/10 text-cobalt border border-cobalt/20">
                      {cap}
                    </span>
                  ))}
                </div>
              </div>

              {c.id === "watsonx_itsm" && (
                <div className="pt-2 border-t border-border-subtle space-y-2">
                  <button
                    onClick={() => watsonxTest.mutate()}
                    disabled={!hasToken || watsonxTest.isPending}
                    className="px-3 py-1.5 rounded-lg text-xs font-mono bg-cobalt/10 text-cobalt border border-cobalt/30 hover:bg-cobalt/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {watsonxTest.isPending ? "Testing…" : "Test Live Connection"}
                  </button>
                  {watsonxTest.data && (
                    <div
                      className={`p-2.5 rounded-lg border text-xs font-mono ${
                        watsonxTest.data.connected
                          ? "bg-emerald/10 border-emerald/30 text-emerald"
                          : "bg-status-red/10 border-status-red/30 text-status-red"
                      }`}
                    >
                      {watsonxTest.data.connected ? (
                        <>
                          🟢 Live — {watsonxTest.data.agentCount} agent(s) registered
                          {watsonxTest.data.agents && watsonxTest.data.agents.length > 0 && (
                            <>: {watsonxTest.data.agents.join(", ")}</>
                          )}
                        </>
                      ) : (
                        <>🔴 {watsonxTest.data.error}</>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Integration Bus Specifications */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚙️</span>
            <h2 className="text-lg font-semibold text-text-primary">Integration Bus &amp; Routing Specs</h2>
          </div>
          <span className="text-xs font-mono text-cobalt px-2.5 py-1 rounded bg-cobalt/10 border border-cobalt/20">
            Cloudant NoSQL Event Bus Active
          </span>
        </div>

        <div className="space-y-2 text-xs font-mono text-text-secondary">
          <p>
            All backend integration services are exposed under both unprefixed and <code className="text-emerald">/api/v1/...</code> alias routes with CORS support for <code className="text-cobalt">http://localhost:3000</code>.
          </p>
          <div className="p-3 rounded-lg bg-glass border border-border-subtle space-y-1">
            <div className="text-text-primary">Cloudant Database: <code className="text-purple">ados_incidents</code> &amp; <code className="text-purple">ados_events</code></div>
            <div className="text-text-primary">Primary Authorization Header: <code className="text-cobalt">Authorization: Bearer dev-local-only-token</code></div>
            <div className="text-text-primary">SSE Event Bus Endpoint: <code className="text-emerald">GET /api/v1/events/stream?token=...</code></div>
          </div>
        </div>
      </div>
    </div>
  );
}
