// documentation/04_Demo_UI_Architecture.md section 2 - HeaderTelemetryBar.

"use client";

import { useEffect, useState } from "react";
import { getToken, setToken } from "@/lib/api";

export function HeaderTelemetryBar() {
  const [token, setTokenState] = useState("");

  useEffect(() => {
    setTokenState(getToken());
  }, []);

  return (
    <header className="flex items-center justify-between border-b border-border-subtle bg-card px-6 py-3">
      <div>
        <div className="text-sm font-semibold text-text-primary">⚡ ADOS</div>
        <div className="text-xs text-text-secondary">Nova Motors · Plant 04 (Austin, TX)</div>
      </div>
      <input
        type="text"
        placeholder="Service token"
        value={token}
        onChange={(e) => {
          setTokenState(e.target.value);
          setToken(e.target.value);
        }}
        className="w-44 rounded-md border border-border-subtle bg-app px-3 py-1.5 text-xs text-text-primary outline-none focus:border-border-accent"
      />
    </header>
  );
}
