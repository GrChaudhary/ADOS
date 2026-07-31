"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getStoredUser, LLMProviderStatus, LLMProvidersResponse } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

const PROVIDER_ICON: Record<string, string> = {
  nemotron: "🟩",
  openai: "🌀",
  anthropic: "🅰️",
};

function statusBadgeClass(s: LLMProviderStatus | LLMProvidersResponse["ollama"]): string {
  if (!s.configured) return "bg-glass text-text-secondary border-border-subtle";
  if (s.connected) return "bg-emerald/20 text-emerald border-emerald/40";
  return "bg-status-red/20 text-status-red border-status-red/40";
}

function ProviderCard({
  status,
  isAdmin,
}: {
  status: LLMProviderStatus;
  isAdmin: boolean;
}) {
  const queryClient = useQueryClient();
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [modelInput, setModelInput] = useState(status.model);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["llm-providers"] });

  const saveMutation = useMutation({
    mutationFn: () => api.saveLLMProviderKey(status.provider, { apiKey: apiKeyInput.trim(), model: modelInput.trim() || undefined }),
    onSuccess: () => {
      setApiKeyInput("");
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteLLMProviderKey(status.provider),
    onSuccess: () => {
      setConfirmingRemove(false);
      invalidate();
    },
  });

  const testMutation = useMutation({
    mutationFn: () => api.testLLMProvider(status.provider),
  });

  return (
    <div className="p-6 rounded-2xl jarvis-glass-card border border-purple-500/30 hover:border-pink-500/60 transition-all duration-300 space-y-4 shadow-lg">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="text-xl">{PROVIDER_ICON[status.provider] ?? "🔌"}</span>
          <h2 className="text-base font-semibold text-text-primary">{status.name}</h2>
        </div>
        <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono border font-semibold ${statusBadgeClass(status)}`}>
          {status.status}
        </span>
      </div>

      <p className="text-xs text-text-secondary">{status.description}</p>

      <div className="p-3 rounded-lg bg-glass border border-border-subtle space-y-2 text-xs font-mono">
        <div className="flex justify-between">
          <span className="text-text-secondary">Failover role:</span>
          <span className="text-cobalt font-medium text-right max-w-[65%]">{status.role}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-secondary">Saved key:</span>
          <span className="text-text-primary">{status.masked_key ?? "— none —"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-secondary">Model:</span>
          <span className="text-purple font-medium truncate max-w-[65%]">{status.model}</span>
        </div>
      </div>

      {!isAdmin && (
        <p className="text-[11px] text-text-secondary italic">Only Admin accounts can add or change platform API keys.</p>
      )}

      {isAdmin && (
        <div className="space-y-2 pt-2 border-t border-border-subtle">
          <div className="space-y-1">
            <label className="text-[11px] font-mono text-text-secondary">API Key</label>
            <input
              type="password"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder={status.configured ? "Enter a new key to replace the saved one" : "Paste your API key"}
              className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/50"
            />
          </div>
          <div className="space-y-1">
            <label className="text-[11px] font-mono text-text-secondary">Model override (optional)</label>
            <input
              type="text"
              value={modelInput}
              onChange={(e) => setModelInput(e.target.value)}
              className="w-full rounded-md border border-border-subtle bg-glass px-3 py-2 text-sm text-text-primary"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              onClick={() => saveMutation.mutate()}
              disabled={!apiKeyInput.trim() || saveMutation.isPending}
              className="px-3 py-1.5 rounded-lg text-xs font-mono bg-cobalt text-white hover:bg-cobalt/80 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saveMutation.isPending ? "Saving…" : "Save Key"}
            </button>
            <button
              onClick={() => testMutation.mutate()}
              disabled={!status.configured || testMutation.isPending}
              className="px-3 py-1.5 rounded-lg text-xs font-mono bg-cobalt/10 text-cobalt border border-cobalt/30 hover:bg-cobalt/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {testMutation.isPending ? "Testing…" : "Test Connection"}
            </button>
            {status.configured && (
              <button
                onClick={() => (confirmingRemove ? deleteMutation.mutate() : setConfirmingRemove(true))}
                disabled={deleteMutation.isPending}
                className={`px-3 py-1.5 rounded-lg text-xs font-mono border transition-all disabled:opacity-40 ${
                  confirmingRemove
                    ? "bg-status-red/20 border-status-red/50 text-status-red animate-pulse"
                    : "bg-glass border-border-subtle text-text-secondary hover:border-status-red/50 hover:text-status-red"
                }`}
              >
                {deleteMutation.isPending ? "Removing…" : confirmingRemove ? "⚠ Confirm Remove" : "Remove"}
              </button>
            )}
          </div>

          {saveMutation.isError && (
            <div className="p-2.5 rounded-lg border text-xs font-mono bg-status-red/10 border-status-red/30 text-status-red">
              {String(saveMutation.error)}
            </div>
          )}
          {testMutation.data && (
            <div
              className={`p-2.5 rounded-lg border text-xs font-mono ${
                testMutation.data.success
                  ? "bg-emerald/10 border-emerald/30 text-emerald"
                  : "bg-status-red/10 border-status-red/30 text-status-red"
              }`}
            >
              {testMutation.data.success ? "🟢" : "🔴"} {testMutation.data.message}
              {testMutation.data.latency_ms != null && <> ({testMutation.data.latency_ms} ms)</>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const hasToken = useHasToken();
  const user = getStoredUser();
  const isAdmin = user?.role === "admin";

  const providersQuery = useQuery<LLMProvidersResponse>({
    queryKey: ["llm-providers"],
    queryFn: api.getLLMProviders,
    refetchInterval: 15000,
    enabled: hasToken,
  });

  return (
    <div className="space-y-8 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-6 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">LLM Provider Settings</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald/10 text-emerald border border-emerald/30">
              Platform-wide
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Bring your own API key for NVIDIA Nemotron, OpenAI, or Anthropic — used by the Reasoning stage
            (Causal Isolation, Substitution, Impact Simulation) with automatic failover across whichever are
            configured. One shared key per provider for the whole deployment, no restart required.
          </p>
        </div>
      </div>

      {!hasToken && <p className="text-sm text-status-red">Log in to view or manage LLM provider settings.</p>}
      {hasToken && providersQuery.isLoading && <p className="text-sm text-text-secondary">Loading provider status…</p>}
      {hasToken && providersQuery.isError && (
        <p className="text-sm text-status-red">Could not load provider settings (check backend &amp; login).</p>
      )}

      {hasToken && providersQuery.data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {providersQuery.data.providers.map((p) => (
              <ProviderCard key={p.provider} status={p} isAdmin={isAdmin} />
            ))}
          </div>

          {/* Ollama — env-only info card, not part of the key-management flow */}
          <div className="p-6 rounded-2xl jarvis-glass-card border border-border-subtle space-y-3 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-xl">💻</span>
                <h2 className="text-base font-semibold text-text-primary">{providersQuery.data.ollama.name}</h2>
              </div>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-mono border font-semibold ${statusBadgeClass(providersQuery.data.ollama)}`}>
                {providersQuery.data.ollama.status}
              </span>
            </div>
            <p className="text-xs text-text-secondary">{providersQuery.data.ollama.description}</p>
            <p className="text-[11px] font-mono text-text-secondary">
              Role: <span className="text-cobalt">{providersQuery.data.ollama.role}</span> — configured via
              LOCAL_LLM_URL / LOCAL_LLM_MODEL in .env, not through this page (no API key involved).
            </p>
          </div>
        </>
      )}
    </div>
  );
}
