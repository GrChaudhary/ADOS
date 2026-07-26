// documentation/04_Demo_UI_Architecture.md section 2 - <AppShell>. Wraps
// every route (root layout.tsx) so all 7 documented screens - mine and
// Phase 5B's - share the same header/sidebar/footer for free.

import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { HeaderTelemetryBar } from "./HeaderTelemetryBar";
import { FooterStatusBar } from "./FooterStatusBar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-app text-text-primary">
      <HeaderTelemetryBar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
      <FooterStatusBar />
    </div>
  );
}
