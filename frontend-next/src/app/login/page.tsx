"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login(username, password);
      router.push("/novus");
    } catch {
      setError("Invalid username or password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-app px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <div className="text-2xl font-bold text-text-primary">⚡ ADOS</div>
          <div className="text-xs text-text-secondary mt-1">Nova Motors · Plant 04 (Bangalore, Karnataka)</div>
        </div>

        <form onSubmit={handleSubmit} className="p-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg space-y-4">
          <div>
            <label className="block text-xs text-text-secondary mb-1">Username</label>
            <input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary text-sm focus:border-cobalt focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary text-sm focus:border-cobalt focus:outline-none"
            />
          </div>

          {error && <p className="text-xs text-status-red">{error}</p>}

          <button
            type="submit"
            disabled={loading || !username || !password}
            className="w-full px-4 py-2.5 rounded-lg bg-cobalt hover:bg-cobalt/90 text-white text-sm font-semibold shadow-md transition-all disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
