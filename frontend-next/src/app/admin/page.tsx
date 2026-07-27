"use client";

import { useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, getToken, setToken, subscribeToTokenChanges, DigitalTwinLine } from "@/lib/api";
import { PERSONAS, useActivePersona, setActivePersonaId } from "@/lib/usePersona";

export default function AdminPage() {
  // useSyncExternalStore (not useState+useEffect) so the server snapshot
  // matches SSR (no window) while the client snapshot reads the real
  // stored token, avoiding a hydration mismatch for a returning user -
  // same reasoning as useHasToken. `tokenDraft` holds in-progress edits
  // before Save; it's separate from the external store on purpose.
  const storedToken = useSyncExternalStore(subscribeToTokenChanges, getToken, () => "");
  const [tokenDraft, setTokenDraft] = useState<string | null>(null);
  const currentToken = tokenDraft ?? (storedToken || "dev-local-only-token");
  const [tokenStatus, setTokenStatus] = useState<string | null>(null);

  const activePersona = useActivePersona();

  // Fetch real backend Digital Twin line configurations
  const twinLinesQuery = useQuery<DigitalTwinLine[]>({
    queryKey: ["admin-digital-twin-lines"],
    queryFn: api.getDigitalTwinLines,
  });

  const lines = twinLinesQuery.data ?? [];

  const handleSaveToken = (e: React.FormEvent) => {
    e.preventDefault();
    setToken(currentToken);
    setTokenDraft(null);
    setTokenStatus("Token updated in localStorage! Re-validating backend auth...");
    twinLinesQuery.refetch().then((res) => {
      if (res.isSuccess) {
        setTokenStatus("Bearer token validated successfully against FastAPI backend! 🟢");
      } else {
        setTokenStatus("Warning: Backend rejected bearer token (401 Unauthorized) 🔴");
      }
    });
  };

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Enterprise Administration &amp; RBAC</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-cobalt/10 text-cobalt border border-cobalt/30">
              Product Module 10 Active
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Role-Based Access Control (RBAC), user persona session switching, live bearer token validation, and plant setup.
          </p>
        </div>
      </div>

      {/* Active Persona Switcher Grid */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">👤</span>
            <h2 className="text-lg font-semibold text-text-primary">Active User Persona Session</h2>
          </div>
          <span className="text-xs font-mono text-emerald px-2 py-0.5 rounded bg-emerald/10 border border-emerald/20 font-bold">
            Active: {activePersona.name} ({activePersona.role})
          </span>
        </div>

        <p className="text-[11px] font-mono text-text-secondary">
          The active persona is the approver identity used on the{" "}
          <code className="text-cobalt">Global Decision Center</code> (/decisions) and gates which decisions it can approve by cost.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-1">
          {PERSONAS.map((p) => {
            const isSelected = p.id === activePersona.id;

            return (
              <div
                key={p.id}
                onClick={() => setActivePersonaId(p.id)}
                className={`p-4 rounded-xl border transition-all cursor-pointer space-y-2 ${
                  isSelected
                    ? "bg-cobalt/20 border-cobalt shadow-lg scale-[1.02]"
                    : "bg-glass border-border-subtle hover:border-border-accent"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{p.avatar}</span>
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">{p.name}</h3>
                    <div className="text-[11px] font-mono text-text-secondary">{p.role}</div>
                  </div>
                </div>

                <div className="pt-2 border-t border-border-subtle text-[11px] font-mono space-y-1 text-text-secondary">
                  <div>Access: <span className="text-cobalt font-semibold">{p.accessLevel}</span></div>
                  <div>
                    Limit:{" "}
                    <span className="text-emerald font-bold">
                      {p.approvalLimitUsd > 0 ? `$${p.approvalLimitUsd.toLocaleString()}` : "None (read-only)"}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Security Auth Token Manager & Live Backend Line Setup Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Auth Token Manager */}
        <div className="lg:col-span-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🔑</span>
              <h2 className="text-lg font-semibold text-text-primary">Service Token Authorization</h2>
            </div>
            <span className="text-xs font-mono text-cobalt px-2 py-0.5 rounded bg-cobalt/10 border border-cobalt/20">
              Bearer Token
            </span>
          </div>

          <form onSubmit={handleSaveToken} className="space-y-4 font-mono text-xs">
            <div>
              <label className="block text-text-secondary mb-1">Service Authorization Token (`ados_service_token`)</label>
              <input
                type="text"
                value={currentToken}
                onChange={(e) => setTokenDraft(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
              />
            </div>

            <button
              type="submit"
              className="w-full px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-emerald text-white hover:bg-emerald/80 transition-all border border-emerald/40"
            >
              Validate &amp; Save Token Live
            </button>

            {tokenStatus && (
              <div className="p-3 rounded-lg bg-glass border border-cobalt/40 text-emerald text-[11px]">
                {tokenStatus}
              </div>
            )}
          </form>
        </div>

        {/* Live Backend Facility Lines */}
        <div className="lg:col-span-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🏭</span>
              <h2 className="text-lg font-semibold text-text-primary">Live Backend Facility Configuration</h2>
            </div>
            <span className="text-xs font-mono text-emerald px-2 py-0.5 rounded bg-emerald/10 border border-emerald/20">
              {lines.length} Lines Online
            </span>
          </div>

          <div className="space-y-2 font-mono text-xs">
            {twinLinesQuery.isLoading && (
              <div className="text-text-secondary py-6 text-center">Loading live line telemetry from backend...</div>
            )}
            {twinLinesQuery.isError && (
              <div className="text-status-red py-6 text-center">Could not load line telemetry (check token).</div>
            )}
            {lines.map((line) => (
              <div key={line.lineId} className="p-3 rounded-lg bg-glass border border-border-subtle flex justify-between items-center">
                <div>
                  <span className="font-bold text-text-primary">{line.lineId}</span>
                  <span className="text-text-secondary text-[11px] ml-2">({line.activeProductSku})</span>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    line.status === "OPERATIONAL"
                      ? "bg-emerald/20 text-emerald"
                      : line.status === "DEGRADED"
                      ? "bg-status-red/20 text-status-red"
                      : "bg-amber/20 text-amber"
                  }`}
                >
                  {line.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
