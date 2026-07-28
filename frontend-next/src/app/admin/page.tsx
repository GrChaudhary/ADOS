"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, AuthUser, DigitalTwinLine, Role } from "@/lib/api";
import { useCurrentUser } from "@/lib/useCurrentUser";

const ROLES: Role[] = ["manager", "executive", "admin", "auditor"];

export default function AdminPage() {
  const currentUser = useCurrentUser();
  const queryClient = useQueryClient();
  const isAdmin = currentUser?.role === "admin";

  const usersQuery = useQuery<AuthUser[]>({
    queryKey: ["admin-users"],
    queryFn: api.listUsers,
    enabled: isAdmin,
  });

  const twinLinesQuery = useQuery<DigitalTwinLine[]>({
    queryKey: ["admin-digital-twin-lines"],
    queryFn: api.getDigitalTwinLines,
    enabled: Boolean(currentUser),
  });
  const lines = twinLinesQuery.data ?? [];

  const [form, setForm] = useState({ username: "", password: "", display_name: "", role: "manager" as Role, approval_limit_usd: 0 });
  const createUserMutation = useMutation({
    mutationFn: () => api.createUser(form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setForm({ username: "", password: "", display_name: "", role: "manager", approval_limit_usd: 0 });
    },
  });

  if (!currentUser) {
    return <p className="text-sm text-text-secondary">Log in to view this page.</p>;
  }

  if (!isAdmin) {
    return (
      <div className="p-5 rounded-xl bg-card/60 border border-status-red/40 text-sm text-status-red">
        User management is restricted to the <code>admin</code> role. You're signed in as{" "}
        <span className="font-semibold">{currentUser.displayName}</span> ({currentUser.role}).
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Enterprise Administration &amp; RBAC</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-cobalt/10 text-cobalt border border-cobalt/30">
              Admin Only
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Real accounts backed by <code className="text-emerald">backend/app/rbac.py</code> — roles and
            per-user approval limits are enforced server-side on every approve/reject/escalate call, not just
            shown here.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* User list */}
        <div className="lg:col-span-7 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">👤</span>
              <h2 className="text-lg font-semibold text-text-primary">Users</h2>
            </div>
            <span className="text-xs font-mono text-text-secondary">{usersQuery.data?.length ?? 0} accounts</span>
          </div>

          {usersQuery.isLoading && <p className="text-xs text-text-secondary">Loading users…</p>}
          {usersQuery.isError && <p className="text-xs text-status-red">Could not load users.</p>}

          <div className="space-y-2 font-mono text-xs">
            {(usersQuery.data ?? []).map((u) => (
              <div key={u.userId} className="p-3 rounded-lg bg-glass border border-border-subtle flex items-center justify-between">
                <div>
                  <span className="font-bold text-text-primary">{u.displayName}</span>
                  <span className="text-text-secondary ml-2">@{u.username}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-cobalt">{u.role}</span>
                  <span className="text-emerald">
                    {u.approvalLimitUsd > 0 ? `$${u.approvalLimitUsd.toLocaleString("en-US")}` : "read-only"}
                  </span>
                  {!u.active && <span className="text-status-red">inactive</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Create user */}
        <div className="lg:col-span-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
          <div className="flex items-center gap-2">
            <span className="text-lg">➕</span>
            <h2 className="text-lg font-semibold text-text-primary">Create User</h2>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              createUserMutation.mutate();
            }}
            className="space-y-3 font-mono text-xs"
          >
            <div>
              <label className="block text-text-secondary mb-1">Username</label>
              <input
                required
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-text-secondary mb-1">Display name</label>
              <input
                required
                value={form.display_name}
                onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-text-secondary mb-1">Password</label>
              <input
                required
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-text-secondary mb-1">Role</label>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
                  className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-text-secondary mb-1">Approval limit ($)</label>
                <input
                  type="number"
                  min={0}
                  value={form.approval_limit_usd}
                  onChange={(e) => setForm({ ...form, approval_limit_usd: Number(e.target.value) })}
                  className="w-full px-3 py-2 rounded-lg bg-glass border border-border-subtle text-text-primary focus:border-cobalt focus:outline-none"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={createUserMutation.isPending}
              className="w-full px-4 py-2 text-xs font-mono font-semibold rounded-lg bg-emerald text-white hover:bg-emerald/80 transition-all border border-emerald/40 disabled:opacity-50"
            >
              {createUserMutation.isPending ? "Creating…" : "Create User"}
            </button>

            {createUserMutation.isError && (
              <div className="p-3 rounded-lg bg-status-red/10 border border-status-red/40 text-status-red text-[11px]">
                {(createUserMutation.error as Error).message}
              </div>
            )}
            {createUserMutation.isSuccess && (
              <div className="p-3 rounded-lg bg-glass border border-emerald/40 text-emerald text-[11px]">
                User created.
              </div>
            )}
          </form>
        </div>
      </div>

      {/* Live Backend Facility Lines */}
      <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
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
            <div className="text-status-red py-6 text-center">Could not load line telemetry.</div>
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
  );
}
