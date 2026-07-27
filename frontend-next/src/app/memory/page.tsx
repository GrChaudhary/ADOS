"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  api,
  DecisionMemoryQuery,
  DecisionMemorySearchResult,
  LearningReplaySummary,
  PolicyPromotionCandidate,
} from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

export default function DecisionMemoryPage() {
  const [searchParams, setSearchParams] = useState<DecisionMemoryQuery>({
    defectType: "",
    plantId: "FAC-P04-L2",
    minConfidence: 0.0,
    limit: 10,
  });
  const hasToken = useHasToken();

  const searchMutation = useMutation<DecisionMemorySearchResult, Error, DecisionMemoryQuery>({
    mutationFn: (query) => api.searchDecisionMemory(query),
  });

  const recalibrationQuery = useQuery<LearningReplaySummary>({
    queryKey: ["learning-recalibration"],
    queryFn: () => api.getLearningRecalibration(0.08),
    enabled: hasToken,
  });

  const promotionQuery = useQuery<PolicyPromotionCandidate[]>({
    queryKey: ["learning-promotion-candidates"],
    queryFn: api.getPromotionCandidates,
    enabled: hasToken,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    searchMutation.mutate(searchParams);
  };

  const searchResults = searchMutation.data;
  const recalibration = recalibrationQuery.data;
  const candidates = promotionQuery.data ?? [];

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Decision Memory &amp; Causal Learning Hub</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-cobalt/10 text-cobalt border border-cobalt/30">
              Vector Precedent RAG
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Historical incident audit trails, Bayesian causal edge weight recalibration, and Tier 0 promotion candidates.
          </p>
        </div>
      </div>

      {/* Precedent Search Bar */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
        <div className="flex items-center gap-2">
          <span className="text-lg">🔍</span>
          <h2 className="text-lg font-semibold text-text-primary">Vector Precedent Similarity Search</h2>
        </div>

        <form onSubmit={handleSearch} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-1">
          <div>
            <label className="block text-xs font-mono text-text-secondary mb-1">Defect Type Filter</label>
            <input
              type="text"
              placeholder="e.g. BORE_TOLERANCE_EXCEEDED"
              value={searchParams.defectType ?? ""}
              onChange={(e) => setSearchParams({ ...searchParams, defectType: e.target.value })}
              className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-dark-900/60 border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-text-secondary mb-1">Plant / Line ID</label>
            <input
              type="text"
              placeholder="FAC-P04-L2"
              value={searchParams.plantId ?? ""}
              onChange={(e) => setSearchParams({ ...searchParams, plantId: e.target.value })}
              className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-dark-900/60 border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-text-secondary mb-1">Min Confidence</label>
            <input
              type="number"
              step="0.1"
              min="0"
              max="1"
              value={searchParams.minConfidence ?? 0}
              onChange={(e) => setSearchParams({ ...searchParams, minConfidence: parseFloat(e.target.value) || 0 })}
              className="w-full px-3 py-2 text-xs font-mono rounded-lg bg-dark-900/60 border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={searchMutation.isPending}
              className="w-full px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-cobalt text-white hover:bg-cobalt/80 transition-all border border-cobalt/40 disabled:opacity-50"
            >
              {searchMutation.isPending ? "Searching..." : "Search Memory RAG"}
            </button>
          </div>
        </form>

        {searchMutation.isError && (
          <p className="text-xs text-status-red">Search failed: {searchMutation.error.message}</p>
        )}

        {/* Precedent Results Display */}
        {searchResults && (
          <div className="mt-4 pt-4 border-t border-border-subtle space-y-3">
            <div className="flex items-center justify-between text-xs font-mono text-text-secondary">
              <span>Total Precedent Matches: {searchResults.totalMatches}</span>
              <span className="text-emerald">High Relevance First</span>
            </div>

            <div className="space-y-2">
              {searchResults.records.map((rec, idx) => (
                <div key={rec.incidentId || idx} className="p-3.5 rounded-lg bg-dark-900/60 border border-border-subtle text-xs font-mono space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-cobalt">{rec.incidentId}</span>
                    <span className="px-2 py-0.5 rounded bg-emerald/20 text-emerald text-[10px]">
                      Relevance: {((searchResults.relevanceScores[idx] ?? 0.94) * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="text-text-primary">
                    Plant: {rec.plantId} | Line: {rec.lineId} | Status: {rec.finalState}
                  </div>
                  <div className="text-text-secondary text-[11px]">
                    Approved By: {rec.approvedBy ?? "Tier 0 Autonomous"} | Cost: ${rec.actualCostUsd?.toLocaleString() ?? "N/A"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Causal Edge Recalibration & Autonomy Candidates */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Causal Recalibration Log */}
        <div className="lg:col-span-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🔄</span>
              <h2 className="text-lg font-semibold text-text-primary">Causal Edge Recalibration</h2>
            </div>
            <span className="text-xs font-mono text-purple px-2 py-0.5 rounded bg-purple/10 border border-purple/20">
              Bayesian Self-Learning
            </span>
          </div>

          <div className="space-y-3 font-mono text-xs text-text-secondary">
            {recalibrationQuery.isLoading && <div>Replaying audit trail…</div>}
            {recalibrationQuery.isError && (
              <div className="text-status-red">Could not load recalibration data (check token).</div>
            )}
            {recalibration && (
              <>
                <div className="p-3 rounded-lg bg-dark-900/60 border border-border-subtle space-y-1">
                  <div>Records Processed: <span className="text-text-primary font-bold">{recalibration.recordsProcessed}</span></div>
                  <div>Causal Edges Updated: <span className="text-emerald font-bold">{recalibration.edgesUpdated}</span></div>
                  <div className="text-[11px] text-text-secondary">Last Replay: {recalibration.timestamp}</div>
                </div>

                <div className="space-y-2 max-h-[260px] overflow-y-auto pr-1">
                  {recalibration.weightAdjustments.length === 0 ? (
                    <div className="text-center py-4">No edge weight adjustments in this replay.</div>
                  ) : (
                    recalibration.weightAdjustments.map((adj, i) => (
                      <div key={i} className="p-2.5 rounded bg-dark-900/40 border border-border-subtle flex items-center justify-between text-[11px]">
                        <span>{(adj.edge_id as string) ?? (adj.condition_id as string) ?? `Edge #${i + 1}`}</span>
                        {typeof adj.delta === "number" && typeof adj.new_weight === "number" && (
                          <span className="text-emerald font-bold">
                            +{adj.delta.toFixed(3)} (weight: {adj.new_weight.toFixed(2)})
                          </span>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Tier 0 Autonomy Promotion Candidates */}
        <div className="lg:col-span-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🚀</span>
              <h2 className="text-lg font-semibold text-text-primary">Tier 0 Autonomy Candidates</h2>
            </div>
            <span className="text-xs font-mono text-emerald px-2 py-0.5 rounded bg-emerald/10 border border-emerald/20">
              {candidates.length} Candidates
            </span>
          </div>

          <div className="space-y-3 max-h-[360px] overflow-y-auto pr-1">
            {promotionQuery.isLoading && <div className="text-xs text-text-secondary py-6 text-center">Loading candidates…</div>}
            {promotionQuery.isError && (
              <div className="text-xs text-status-red py-6 text-center">Could not load candidates (check token).</div>
            )}
            {candidates.map((cand) => (
              <div key={cand.candidateId} className="p-3.5 rounded-lg bg-dark-900/60 border border-border-subtle space-y-2 text-xs font-mono">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-text-primary">{cand.decisionClassName}</span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] ${
                      cand.isEligible ? "bg-emerald/20 text-emerald border border-emerald/40" : "bg-amber/20 text-amber border border-amber/40"
                    }`}
                  >
                    {cand.isEligible ? "ELIGIBLE FOR TIER 0" : "EVALUATING"}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px] text-text-secondary">
                  <div>Acceptance: <span className="text-emerald font-bold">{(cand.operatorAcceptanceRate * 100).toFixed(0)}%</span></div>
                  <div>Avg Conf: <span className="text-cobalt font-bold">{(cand.avgConfidence * 100).toFixed(0)}%</span></div>
                </div>

                <p className="text-[11px] text-text-secondary">{cand.promotionRationale}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
