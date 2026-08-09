"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getStoredUser, LLMProviderStatus, LLMProvidersResponse } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

const PROVIDER_ICON: Record<string, string> = {
  nemotron: "🟩",
  groq: "⚡",
  openai: "🌀",
  anthropic: "🅰️",
};


function statusBadgeClass(s: LLMProviderStatus | LLMProvidersResponse["ollama"]): string {
  if (!s.configured) return "bg-glass text-text-secondary border-border-subtle";
  if (s.connected) return "bg-emerald/20 text-emerald border-emerald/40";
  return "bg-status-red/20 text-status-red border-status-red/40";
}

function ActiveProviderSelector({
  activeProvider,
  activeSource,
  isAdmin,
}: {
  activeProvider: string;
  activeSource: string;
  isAdmin: boolean;
}) {
  const queryClient = useQueryClient();
  const setActiveMutation = useMutation({
    mutationFn: (provider: string) => api.setActiveLLMProvider(provider),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
    },
  });

  const options = [
    { id: "auto", label: "Automatic Failover", icon: "🔄", desc: "Try Nemotron ➔ Groq ➔ OpenAI ➔ Anthropic ➔ Ollama" },
    { id: "groq", label: "Groq Cloud", icon: "⚡", desc: "Ultra-low latency Llama-3.3 70B" },
    { id: "nemotron", label: "NVIDIA Nemotron", icon: "🟩", desc: "Super-49B-v1 high precision" },
    { id: "ollama", label: "Ollama (Local)", icon: "🦙", desc: "Local Qwen sandboxed model" },
  ];

  return (
    <div className="p-6 rounded-2xl jarvis-glass-card border border-purple-500/40 space-y-4 shadow-xl bg-gradient-to-r from-purple-950/20 via-background-dark to-cobalt-950/20">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">🎯</span>
            <h2 className="text-base font-semibold text-text-primary">Primary Reasoning LLM Engine</h2>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-500/20 text-purple border border-purple-500/40">
              ACTIVE: {activeProvider.toUpperCase()} ({activeSource})
            </span>
          </div>
          <p className="text-xs text-text-secondary mt-1">
            Choose which LLM powers the ADOS Causal Isolation &amp; Reasoning Engine. Dynamic runtime switching takes effect instantly across all agents.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
        {options.map((opt) => {
          const isSelected = activeProvider === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              disabled={!isAdmin || setActiveMutation.isPending}
              onClick={() => setActiveMutation.mutate(opt.id)}
              className={`p-3.5 rounded-xl text-left border transition-all duration-200 flex flex-col justify-between ${
                isSelected
                  ? "bg-purple-600/20 border-purple-500 text-text-primary shadow-lg shadow-purple-500/10 ring-1 ring-purple-500"
                  : "bg-glass border-border-subtle hover:border-purple-500/50 text-text-secondary"
              } ${!isAdmin ? "cursor-not-allowed opacity-75" : ""}`}
            >
              <div className="flex items-center justify-between">
                <span className="text-lg">{opt.icon}</span>
                {isSelected && (
                  <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-emerald/20 text-emerald border border-emerald/40">
                    SELECTED
                  </span>
                )}
              </div>
              <div className="mt-2">
                <p className="text-xs font-semibold text-text-primary">{opt.label}</p>
                <p className="text-[10px] text-text-secondary line-clamp-2 mt-0.5">{opt.desc}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
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
  const queryClient = useQueryClient();

  const providersQuery = useQuery<LLMProvidersResponse>({
    queryKey: ["llm-providers"],
    queryFn: api.getLLMProviders,
    refetchInterval: 15000,
    enabled: hasToken,
  });

  const toggleThinkingMutation = useMutation({
    mutationFn: (enabled: boolean) => api.toggleThinkingMode(enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
    },
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
          <ActiveProviderSelector
            activeProvider={providersQuery.data.activeProvider || "auto"}
            activeSource={providersQuery.data.activeProviderSource || "auto"}
            isAdmin={isAdmin}
          />

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {providersQuery.data.providers.map((p) => (
              <ProviderCard key={p.provider} status={p} isAdmin={isAdmin} />
            ))}
          </div>


          {/* Ollama — info card with Thinking Mode Toggle */}
          <div className="p-6 rounded-2xl jarvis-glass-card border border-border-subtle space-y-4 shadow-lg">
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

            {/* Thinking Mode Toggle */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-purple-950/20 border border-purple-500/20">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-text-primary">Thinking Mode (Qwen / Local LLM)</span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${
                      providersQuery.data.ollama.thinkingEnabled
                        ? "bg-purple-500/20 text-purple border-purple-500/40"
                        : "bg-emerald/10 text-emerald border-emerald/30"
                    }`}
                  >
                    {providersQuery.data.ollama.thinkingEnabled ? "THINKING ON" : "DIRECT / OFF"}
                  </span>
                </div>
                <p className="text-xs text-text-secondary">
                  Controls whether local Qwen models execute an internal reasoning pass before responding. When OFF (default), response time is significantly faster and token usage is reduced.
                </p>
              </div>
              {isAdmin && (
                <button
                  type="button"
                  disabled={toggleThinkingMutation.isPending}
                  onClick={() => toggleThinkingMutation.mutate(!providersQuery.data.ollama.thinkingEnabled)}
                  className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                    providersQuery.data.ollama.thinkingEnabled ? "bg-purple-600" : "bg-gray-700"
                  } ${toggleThinkingMutation.isPending ? "opacity-50 cursor-not-allowed" : ""}`}
                >
                  <span
                    className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                      providersQuery.data.ollama.thinkingEnabled ? "translate-x-5" : "translate-x-0"
                    }`}
                  />
                </button>
              )}
            </div>

            <p className="text-[11px] font-mono text-text-secondary">
              Role: <span className="text-cobalt">{providersQuery.data.ollama.role}</span> — configured via
              LOCAL_LLM_URL / LOCAL_LLM_MODEL in .env (no API key involved).
            </p>
          </div>
        </>
      )}
    </div>
  );
}
