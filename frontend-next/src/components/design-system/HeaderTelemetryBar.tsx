"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession } from "@/lib/api";
import { useCurrentUser } from "@/lib/useCurrentUser";
import { NovusHeaderIcon } from "./NovusHeaderIcon";
import portalStyles from "./PortalTransition.module.css";

const NOVUS_STUDIO_DEST = "/novus-studio#signal";

export function HeaderTelemetryBar() {
  const currentUser = useCurrentUser();
  const pathname = usePathname();
  const router = useRouter();

  const isExecutive = pathname?.startsWith("/executive");
  const isNovusLab =
    pathname === "/" || pathname === "/novus" || pathname === "/digital-twin" || pathname?.startsWith("/novus-studio");

  const [rippling, setRippling] = useState(false);
  const [portalOpen, setPortalOpen] = useState(false);
  const [flashVisible, setFlashVisible] = useState(false);
  const navigateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function openNovusStudioPortal() {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion) {
      router.push(NOVUS_STUDIO_DEST);
      return;
    }

    setRippling(true);
    setTimeout(() => setRippling(false), 600);

    setPortalOpen(true);
    setTimeout(() => setFlashVisible(true), 180);

    navigateTimer.current = setTimeout(() => {
      router.push(NOVUS_STUDIO_DEST);
    }, 650);
  }

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
        <button
          type="button"
          onClick={openNovusStudioPortal}
          className={`${portalStyles.rippleWrap} px-5 py-2 rounded-xl font-orbitron font-bold text-xs tracking-wider transition-all flex items-center gap-2 cursor-pointer ${
            isNovusLab ? "novus-tab-active" : "novus-tab-inactive"
          }`}
        >
          <span className={`${portalStyles.ripple} ${rippling ? portalStyles.rippleActive : ""}`} aria-hidden="true" />
          <span>NOVUS STUDIO</span>
          {isNovusLab && <span className="w-1.5 h-1.5 rounded-full bg-pink-300 animate-pulse" />}
        </button>
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

      {/* Kinetic opening portal — button ripple already fires inline above;
          this is the glass curtain + telemetry flash before navigating to
          /novus-studio#signal. Unmounts on route change along with the
          rest of the page, so no cleanup is needed on success. */}
      <div className={`${portalStyles.overlay} ${portalOpen ? portalStyles.overlayOpen : ""}`} aria-hidden="true">
        <span className={`${portalStyles.flash} ${flashVisible ? portalStyles.flashVisible : ""}`}>
          INITIALIZING NOVUS APPLIED-AI STUDIO // 01 SENSING STREAM ACTIVE
        </span>
      </div>
    </header>
  );
}

