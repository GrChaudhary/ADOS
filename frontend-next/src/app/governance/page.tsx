"use client";

export default function GovernancePolicyPage() {
  // Dollar-threshold tier matrix numbers from orchestrate/governance.py
  const LOW_EXPOSURE_MAX_USD = 25000;
  const HIGH_EXPOSURE_MIN_USD = 250000;
  const TIER0_CONFIDENCE_THRESHOLD = 0.90;

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Governance Policy &amp; Autonomy Administration</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-purple/10 text-purple border border-purple/30">
              Layer 5 Policy Engine Active
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Financial exposure tier thresholds, autonomous decision policy rules, and multi-executive override controls.
          </p>
        </div>

        {/* Decorative Emergency Override Soft Lock */}
        <div className="flex items-center gap-3 p-3 rounded-lg bg-dark-900/60 border border-border-subtle text-xs font-mono">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald animate-pulse" />
            <span className="text-text-secondary">Autonomy Engine:</span>
            <span className="text-emerald font-bold">ARMED</span>
          </div>
          <div className="pl-3 border-l border-border-subtle flex items-center gap-2 opacity-60 cursor-not-allowed">
            <span className="text-text-secondary">Master Lock:</span>
            <div className="w-8 h-4 rounded-full bg-border-subtle p-0.5 relative">
              <div className="w-3 h-3 rounded-full bg-slate-400" />
            </div>
            <span className="text-[10px] text-text-secondary">(Read-only)</span>
          </div>
        </div>
      </div>

      {/* Dollar-Threshold Tier Matrix (Reference: orchestrate/governance.py) */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚖️</span>
            <h2 className="text-lg font-semibold text-text-primary">Dollar-Threshold Governance Matrix</h2>
          </div>
          <span className="text-xs font-mono text-text-secondary">
            Source: <code className="text-cobalt">orchestrate/governance.py</code>
          </span>
        </div>

        <p className="text-xs text-text-secondary">
          The Governance Policy Engine evaluates every capability call against financial exposure boundaries and AI agent confidence.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
          {/* Tier 0 Card */}
          <div className="p-4 rounded-xl bg-dark-900/60 border border-emerald/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-emerald/20 text-emerald border border-emerald/40">
                TIER 0
              </span>
              <span className="text-xs font-mono text-emerald font-semibold">Fully Autonomous</span>
            </div>
            <div className="space-y-1 font-mono text-xs">
              <div className="text-text-secondary">Max Cost: <span className="text-text-primary font-bold">&lt; ${LOW_EXPOSURE_MAX_USD.toLocaleString()}</span></div>
              <div className="text-text-secondary">Min Confidence: <span className="text-text-primary font-bold">&gt; {(TIER0_CONFIDENCE_THRESHOLD * 100).toFixed(0)}%</span></div>
            </div>
            <p className="text-[11px] text-text-secondary">
              Dispatches execution immediately to SAP ERP &amp; ServiceNow without human intervention.
            </p>
          </div>

          {/* Tier 1 Card */}
          <div className="p-4 rounded-xl bg-dark-900/60 border border-cobalt/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-cobalt/20 text-cobalt border border-cobalt/40">
                TIER 1
              </span>
              <span className="text-xs font-mono text-cobalt font-semibold">Engineer 1-Click</span>
            </div>
            <div className="space-y-1 font-mono text-xs">
              <div className="text-text-secondary">Cost Range: <span className="text-text-primary font-bold">${LOW_EXPOSURE_MAX_USD.toLocaleString()} – ${HIGH_EXPOSURE_MIN_USD.toLocaleString()}</span></div>
              <div className="text-text-secondary">Approval Queue: <span className="text-text-primary font-bold">1 Engineer Click</span></div>
            </div>
            <p className="text-[11px] text-text-secondary">
              Holds execution in ApprovalQueue until Quality Engineer or Plant Manager approves Option A/B.
            </p>
          </div>

          {/* Tier 2 Card */}
          <div className="p-4 rounded-xl bg-dark-900/60 border border-purple/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="px-2.5 py-0.5 rounded text-xs font-mono font-bold bg-purple/20 text-purple border border-purple/40">
                TIER 2
              </span>
              <span className="text-xs font-mono text-purple font-semibold">Executive Dual Signature</span>
            </div>
            <div className="space-y-1 font-mono text-xs">
              <div className="text-text-secondary">Cost Range: <span className="text-text-primary font-bold">&gt; ${HIGH_EXPOSURE_MIN_USD.toLocaleString()}</span></div>
              <div className="text-text-secondary">Critical Actions: <span className="text-text-primary font-bold">Line Shutdown / Safety</span></div>
            </div>
            <p className="text-[11px] text-text-secondary">
              Requires VP Operations and Finance dual signature override for major capital changes.
            </p>
          </div>
        </div>
      </div>

      {/* Governance Rule Enforcements */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">📋</span>
            <h2 className="text-lg font-semibold text-text-primary">Enforced Policy Rules</h2>
          </div>
          <span className="text-xs font-mono text-emerald px-2 py-0.5 rounded bg-emerald/10 border border-emerald/20">
            Active Guardrails
          </span>
        </div>

        <div className="space-y-2 text-xs font-mono">
          {[
            { rule: "POL-001", desc: "All SAP Purchase Orders exceeding $25,000 require Tier 1 human approval.", status: "ACTIVE" },
            { rule: "POL-002", desc: "Preemption lock holds factory line until active incident is completely resolved.", status: "ACTIVE" },
            { rule: "POL-003", desc: "Decisions with confidence < 90% are automatically demoted to Tier 1 holding queue.", status: "ACTIVE" },
            { rule: "POL-004", desc: "Supplier switch requires stock verification against B2B Marketplace API before PO issue.", status: "ACTIVE" },
          ].map((item) => (
            <div key={item.rule} className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle flex items-center justify-between gap-4">
              <div>
                <span className="font-bold text-cobalt">{item.rule}:</span> <span className="text-text-primary">{item.desc}</span>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] bg-emerald/20 text-emerald font-bold">{item.status}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
