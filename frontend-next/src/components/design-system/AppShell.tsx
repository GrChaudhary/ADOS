"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { HeaderTelemetryBar } from "./HeaderTelemetryBar";
import { FooterStatusBar } from "./FooterStatusBar";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isLandingPage =
    pathname === "/" || pathname === "/novus" || pathname === "/jarvis" || pathname === "/login" || pathname === "/novus-studio";

  if (isLandingPage) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-[#070514] text-white flex flex-col relative overflow-x-hidden font-sans">
      {/* Background ambient lighting effects for landing page consistency */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[600px] bg-gradient-to-b from-purple-900/25 via-pink-600/10 to-transparent blur-[120px] pointer-events-none rounded-full" />
      <div className="absolute top-[600px] left-[-200px] w-[600px] h-[600px] bg-gradient-to-tr from-cyan-600/15 to-purple-800/15 blur-[140px] pointer-events-none rounded-full" />

      <HeaderTelemetryBar />

      <div className="flex flex-1 relative z-10">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6 md:p-8">{children}</main>
      </div>

      <FooterStatusBar />
    </div>
  );
}


