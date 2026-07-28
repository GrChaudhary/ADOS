// documentation/03_Design_System.md section 5.2 - Multi-Option
// Recommendation Card (Option A/B/C). Data shape matches
// executive/models.py's IncidentOption (Phase 3) exactly - see
// src/lib/api.ts's IncidentOption type.

import type { IncidentOption } from "@/lib/api";

interface OptionCardProps {
  option: IncidentOption;
  onApprove?: () => void;
  approving?: boolean;
}

function starString(rating: number): string {
  const clamped = Math.max(1, Math.min(5, rating));
  return "★".repeat(clamped) + "☆".repeat(5 - clamped);
}

export function OptionCard({ option, onApprove, approving }: OptionCardProps) {
  return (
    <div
      className={`rounded-lg border bg-card p-4 ${option.isRecommended ? "border-emerald" : "border-border-subtle"}`}
    >
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-cobalt text-xs font-bold text-white">
          {option.letter}
        </span>
        <span className="font-semibold text-text-primary">{option.name}</span>
      </div>
      <div className="mt-2 text-amber">{starString(option.starRating)}</div>
      <div className="mt-2 space-y-1 text-xs text-text-secondary">
        <div>Cost: ${option.estimatedCostUsd.toLocaleString("en-US")}</div>
        <div>Downtime: {option.downtimeMinutes} min</div>
        <div>Quality Risk: {Math.round(option.qualityRiskScore * 100)}%</div>
        <div>Savings vs. costliest: ${option.savingsUsd.toLocaleString("en-US")}</div>
      </div>
      {onApprove && (
        <button
          type="button"
          onClick={onApprove}
          disabled={approving}
          className={`mt-4 w-full rounded-md px-3 py-2 text-sm font-semibold transition-all disabled:opacity-50 ${
            option.isRecommended
              ? "bg-cobalt text-white hover:bg-cobalt/85 shadow-md shadow-cobalt/10"
              : "border border-cobalt text-cobalt bg-transparent hover:bg-cobalt/10"
          }`}
        >
          {approving ? "Approving…" : `Approve Option ${option.letter}`}
        </button>
      )}
    </div>
  );
}
