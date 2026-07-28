"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession } from "@/lib/api";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { NovusHeaderIcon } from "./NovusHeaderIcon";

export function HeaderTelemetryBar() {
  const currentUser = useCurrentUser();
  const pathname = usePathname();
  const router = useRouter();

  const isExecutive = pathname?.startsWith("/executive");
  const isNovusLab = pathname === "/" || pathname === "/novus" || pathname === "/digital-twin";

  return (
    <header className="relative z-30 border-b border-purple-500/20 bg-[#08051a]/80 backdrop-blur-xl px-6 py-3 flex items-center justify-between shadow-2xl">
      {/* Brand Icon & Title */}
      <Link href="/" className="flex items-center gap-3 group cursor-pointer">
        <NovusHeaderIcon size="sm" />
        <div>
          <div className="flex items-center gap-1">
            <span className="font-orbitron font-extrabold text-base tracking-wider text-white">
              NOVUS <span className="text-pink-500">ADOS</span>
            </span>
          </div>
          <span className="text-[9px] font-mono tracking-widest text-purple-300/60 uppercase block">
            ENTERPRISE DECISION OS
          </span>
        </div>
      </Link>

      {/* 2 TOP TABS SWITCHER */}
      <div className="flex items-center gap-2 p-1 rounded-2xl bg-purple-950/40 border border-purple-500/30 backdrop-blur-md shadow-inner">
        <Link
          href="/executive/enterprise"
          className={`px-5 py-2 rounded-xl font-orbitron font-bold text-xs tracking-wider transition-all flex items-center gap-2 ${
            isExecutive ? "novus-tab-active" : "novus-tab-inactive"
          }`}
        >
          <span>EXECUTIVE DASHBOARD</span>
          {isExecutive && <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />}
        </Link>
        <Link
          href="/"
          className={`px-5 py-2 rounded-xl font-orbitron font-bold text-xs tracking-wider transition-all flex items-center gap-2 ${
            isNovusLab ? "novus-tab-active" : "novus-tab-inactive"
          }`}
        >
          <span>NOVUS LAB</span>
          {isNovusLab && <span className="w-1.5 h-1.5 rounded-full bg-pink-300 animate-pulse" />}
        </Link>
      </div>

      {/* Plant Telemetry & Session Identity */}
      <div className="flex items-center gap-4 text-xs font-mono">
        <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-purple-950/50 border border-purple-500/20 text-purple-200">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>Nova Motors · Plant 04</span>
        </div>
        {currentUser ? (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-purple-950/50 border border-purple-500/20 text-purple-200">
            <span className="text-white font-semibold">{currentUser.displayName}</span>
            <span className="text-purple-300/60 uppercase text-[10px]">{currentUser.role}</span>
            <button
              onClick={() => {
                clearSession();
                router.push("/login");
              }}
              className="text-purple-300/60 hover:text-pink-400 transition-colors"
              title="Log out"
            >
              ⏻
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="px-3 py-1.5 rounded-xl bg-pink-600 hover:bg-pink-500 text-white font-semibold shadow-inner transition-colors"
          >
            Log in
          </Link>
        )}
      </div>
    </header>
  );
}

