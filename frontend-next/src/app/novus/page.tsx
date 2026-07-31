"use client";

import React, { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { NovusParticleOrb } from "@/components/novus/NovusParticleOrb";
import { NovusHeaderIcon } from "@/components/design-system/NovusHeaderIcon";
import { ActiveTheoryFeaturesShowcase } from "@/components/novus/ActiveTheoryFeaturesShowcase";
import { Cylinder3DArchitectureCarousel } from "@/components/novus/Cylinder3DArchitectureCarousel";
import portalStyles from "@/components/design-system/PortalTransition.module.css";

const NOVUS_STUDIO_DEST = "/novus-studio#signal";

export default function NovusLandingPage() {
  const router = useRouter();

  const [rippling, setRippling] = useState(false);
  const [portalOpen, setPortalOpen] = useState(false);
  const [flashVisible, setFlashVisible] = useState(false);
  const [integrationsOpen, setIntegrationsOpen] = useState(false);
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

  // Calculator State for MTTR & Cost Savings Impact
  const [monthlyIncidents, setMonthlyIncidents] = useState<number>(45);
  const [factoryLines, setFactoryLines] = useState<number>(6);

  // Math based on ADOS production benchmarks (-84% MTTR, average $4,500/hr downtime cost)
  const baselineMttrHours = 4.2; // Standard human coordination MTTR
  const adosMttrHours = 0.65; // ADOS compressed MTTR (39 mins)
  const hoursSavedPerIncident = baselineMttrHours - adosMttrHours;

  const totalDowntimeHoursSaved = (monthlyIncidents * hoursSavedPerIncident).toFixed(1);
  const ProtectedRevenue = ((monthlyIncidents * hoursSavedPerIncident * 4850) / 1000).toFixed(1); // in $K
  const autonomousRatio = Math.min(94.5, 65 + factoryLines * 3.5).toFixed(1);

  return (
    <div className="min-h-screen bg-[#070514] text-white selection:bg-pink-500 selection:text-white relative overflow-x-hidden font-sans">
      {/* Background ambient lighting effects */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[600px] bg-gradient-to-b from-purple-900/30 via-pink-600/15 to-transparent blur-[120px] pointer-events-none rounded-full" />
      <div className="absolute top-[800px] left-[-200px] w-[600px] h-[600px] bg-gradient-to-tr from-cyan-600/15 to-purple-800/15 blur-[140px] pointer-events-none rounded-full" />
      <div className="absolute top-[1600px] right-[-200px] w-[700px] h-[700px] bg-gradient-to-bl from-pink-600/15 to-indigo-800/15 blur-[150px] pointer-events-none rounded-full" />

      {/* ==================== 1. HEADER ==================== */}
      <header className="relative z-30 max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
        {/* Brand Icon & Title */}
        <div className="flex items-center gap-3">
          <NovusHeaderIcon size="md" />
          <div>
            <div className="flex items-center gap-1">
              <span className="font-orbitron font-extrabold text-xl tracking-wider text-white">
                NOVUS <span className="text-pink-500">ADOS</span>
              </span>
            </div>
            <span className="text-[10px] font-mono tracking-widest text-purple-300/60 uppercase block">
              ENTERPRISE DECISION OS
            </span>
          </div>
        </div>

        {/* 2 TOP TABS SWITCHER */}
        <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-purple-950/60 border border-purple-500/40 backdrop-blur-xl shadow-2xl">
          <Link
            href="/executive/enterprise"
            className="px-6 py-2.5 rounded-xl font-orbitron font-bold text-xs tracking-wider transition-all novus-tab-inactive hover:scale-105"
          >
            EXECUTIVE DASHBOARD
          </Link>
          <button
            type="button"
            onClick={openNovusStudioPortal}
            className={`${portalStyles.rippleWrap} px-6 py-2.5 rounded-xl font-orbitron font-bold text-xs tracking-wider transition-all novus-tab-active flex items-center gap-2 cursor-pointer`}
          >
            <span className={`${portalStyles.ripple} ${rippling ? portalStyles.rippleActive : ""}`} aria-hidden="true" />
            <span>NOVUS STUDIO</span>
            <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
          </button>
        </div>

        {/* Secondary Navigation Links */}
        <nav className="hidden lg:flex items-center gap-6 text-xs font-mono text-purple-200/70">
          <Link href="/digital-twin" className="hover:text-white transition-colors">
            Digital Twin
          </Link>
          <a href="#features" className="hover:text-white transition-colors">
            Features
          </a>
          <a href="#architecture" className="hover:text-white transition-colors">
            Architecture
          </a>
          <button
            type="button"
            onClick={() => setIntegrationsOpen(true)}
            className="hover:text-white transition-colors cursor-pointer bg-none border-none text-xs font-mono text-purple-200/70"
          >
            Integrations
          </button>
        </nav>
      </header>

      {/* Glassmorphic Integrations Pop-Up Modal (Item 3 Requirement) */}
      {integrationsOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-black/80 backdrop-blur-2xl animate-fade-in">
          <div className="w-full max-w-2xl bg-[#0d0926]/95 border border-cyan-500/40 rounded-3xl p-8 shadow-2xl relative">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-white/10 font-mono">
              <div className="flex items-center gap-3">
                <span className="text-cyan-400 font-bold text-sm">CONNECTED ENTERPRISE INTEGRATIONS</span>
                <span className="px-2.5 py-0.5 rounded-full text-[10px] bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-bold">
                  ● 4 SYSTEMS ACTIVE
                </span>
              </div>
              <button
                type="button"
                onClick={() => setIntegrationsOpen(false)}
                className="w-8 h-8 rounded-full border border-white/20 text-white/70 hover:text-white hover:border-white transition-all flex items-center justify-center text-xs"
              >
                ✕
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs mb-6">
              <div className="p-4 rounded-2xl bg-white/5 border border-white/10 flex flex-col gap-2">
                <div className="flex justify-between items-center text-cyan-300 font-bold">
                  <span>ServiceNow Table API</span>
                  <span className="text-[10px] text-emerald-400">● OAuth2</span>
                </div>
                <p className="text-purple-200/70 text-[11px]">Direct automated Incident & Change Request creation (INC0094821)</p>
              </div>

              <div className="p-4 rounded-2xl bg-white/5 border border-white/10 flex flex-col gap-2">
                <div className="flex justify-between items-center text-amber-300 font-bold">
                  <span>SAP ERP RFC Adapter</span>
                  <span className="text-[10px] text-emerald-400">● RFC Conn</span>
                </div>
                <p className="text-purple-200/70 text-[11px]">Real-time inventory reservation & spindle part hold (SAP-RES-9912)</p>
              </div>

              <div className="p-4 rounded-2xl bg-white/5 border border-white/10 flex flex-col gap-2">
                <div className="flex justify-between items-center text-purple-300 font-bold">
                  <span>IBM watsonx ADK</span>
                  <span className="text-[10px] text-emerald-400">● gRPC</span>
                </div>
                <p className="text-purple-200/70 text-[11px]">Orchestrate agent tool binding stream & causal reasoning DAG</p>
              </div>

              <div className="p-4 rounded-2xl bg-white/5 border border-white/10 flex flex-col gap-2">
                <div className="flex justify-between items-center text-pink-300 font-bold">
                  <span>Kafka Telemetry Stream</span>
                  <span className="text-[10px] text-emerald-400">● 14K msg/s</span>
                </div>
                <p className="text-purple-200/70 text-[11px]">Low-latency optical displacement & micrometer sensor stream</p>
              </div>
            </div>

            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setIntegrationsOpen(false)}
                className="px-6 py-2 rounded-full bg-cyan-500 text-black font-mono text-xs font-bold hover:bg-cyan-400 transition-all"
              >
                CLOSE OVERLAY ↗
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Kinetic opening portal — button ripple already fires inline above;
          this is the glass curtain + telemetry flash before navigating to
          /novus-studio#signal. */}
      <div className={`${portalStyles.overlay} ${portalOpen ? portalStyles.overlayOpen : ""}`} aria-hidden="true">
        <span className={`${portalStyles.flash} ${flashVisible ? portalStyles.flashVisible : ""}`}>
          INITIALIZING NOVUS APPLIED-AI STUDIO // 01 SENSING STREAM ACTIVE
        </span>
      </div>

      {/* ==================== 2. HERO SECTION ==================== */}
      <section className="relative z-20 max-w-7xl mx-auto px-6 pt-8 pb-16 text-center">
        {/* Capsule Tagline */}
        <div className="inline-flex items-center gap-2 px-5 py-2 rounded-full jarvis-glass-card border border-purple-500/30 text-xs font-mono text-pink-300 mb-8 backdrop-blur-md">
          <span className="w-2 h-2 rounded-full bg-pink-500 animate-ping" />
          <span>AUTONOMOUS DEFECT & ORCHESTRATION SYSTEM (ADOS)</span>
        </div>

        {/* Main Display Title */}
        <h1 className="text-5xl sm:text-7xl md:text-8xl lg:text-9xl font-orbitron font-black tracking-tight leading-none mb-6 select-none">
          <span className="cyber-glitch-text inline-block">
            <span className="text-white tracking-widest">NOVUS </span>
            <span className="text-pink-500 jarvis-pink-glow tracking-widest">ADOS</span>
          </span>
        </h1>

        {/* Subtext reflecting 000-vision.md */}
        <p className="max-w-3xl mx-auto text-sm sm:text-base text-purple-200/70 font-sans leading-relaxed mb-10">
          Compressing the gap between <strong className="text-white">defect detection</strong> and{" "}
          <strong className="text-pink-400">production recovery</strong>. AI decides{" "}
          <em className="text-cyan-400 font-serif">WHAT</em> should happen — enterprise integrations execute{" "}
          <em className="text-purple-300 font-serif">HOW</em> it happens.
        </p>

        {/* 3D Particle Orb Canvas Container */}
        <div className="my-6">
          <NovusParticleOrb />
        </div>
      </section>


      {/* ==================== 3. CONNECTORS & INTEGRATION HUB ==================== */}
      <section id="integrations" className="relative z-20 border-y border-purple-500/20 bg-purple-950/20 backdrop-blur-md py-8">
        <div className="max-w-7xl mx-auto px-6">
          <p className="text-center text-xs font-mono tracking-widest text-purple-300/50 uppercase mb-6">
            ENTERPRISE SYSTEMS OF RECORD & CAPABILITY-DRIVEN CONNECTORS
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-8 items-center justify-items-center opacity-85 hover:opacity-100 transition-opacity">
            <div className="flex items-center gap-2 text-sm font-orbitron font-bold text-cyan-300 tracking-wider">
              <span>⚡</span> IBM watsonx
            </div>
            <div className="flex items-center gap-2 text-sm font-orbitron font-bold text-blue-300 tracking-wider">
              <span>🏢</span> SAP ERP
            </div>
            <div className="flex items-center gap-2 text-sm font-orbitron font-bold text-emerald-300 tracking-wider">
              <span>🛠️</span> ServiceNow
            </div>
            <div className="flex items-center gap-2 text-sm font-orbitron font-bold text-purple-300 tracking-wider">
              <span>☁️</span> Cloudant NoSQL
            </div>
            <div className="flex items-center gap-2 text-sm font-orbitron font-bold text-pink-300 tracking-wider">
              <span>🔄</span> Redis Bus
            </div>
            <div className="flex items-center gap-2 text-sm font-orbitron font-bold text-amber-300 tracking-wider">
              <span>🏭</span> OPC-UA / MES
            </div>
          </div>
        </div>
      </section>

      {/* ==================== 4. PROJECT FEATURES SECTION ==================== */}
      <section id="features" className="relative z-20 max-w-7xl mx-auto px-6 py-24">
        <div className="text-center mb-16">
          <span className="text-xs font-mono tracking-widest text-pink-400 uppercase block mb-2">
            CORE CAPABILITIES OF NOVUS ADOS
          </span>
          <h2 className="text-3xl sm:text-5xl font-syne font-extrabold italic jarvis-gradient-text tracking-wide mb-4">
            Autonomous Defect-to-Recovery Loop
          </h2>
          <p className="max-w-2xl mx-auto text-sm text-purple-200/60 font-sans">
            Eliminating human coordination tax through 8 specialist AI agents, tiered autonomy governance, and explainable decision memory.
          </p>
        </div>

        {/* Active Theory Style Interactive Showcase */}
        <ActiveTheoryFeaturesShowcase />
      </section>

      {/* ==================== 5. 6-LAYER ARCHITECTURE BREAKDOWN ==================== */}
      <section id="architecture" className="relative z-20 max-w-7xl mx-auto px-6 py-16">
        <div className="p-8 rounded-3xl jarvis-glass-card border border-purple-500/30 bg-[#0c0824]/90 backdrop-blur-xl">
          <div className="text-center mb-10">
            <span className="text-xs font-mono tracking-widest text-cyan-400 uppercase block mb-2">
              6-LAYER ENTERPRISE ARCHITECTURE
            </span>
            <h2 className="text-3xl font-orbitron font-bold text-white">
              The NOVUS ADOS Decision Stack
            </h2>
          </div>

          {/* Interactive 3D Cylinder Carousel */}
          <Cylinder3DArchitectureCarousel />
        </div>
      </section>

      {/* ==================== 6. MTTR & ROI CALCULATOR ==================== */}
      <section className="relative z-20 max-w-7xl mx-auto px-6 py-16">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
          {/* Left Column: ROI Impact Description */}
          <div className="lg:col-span-5 space-y-6">
            <div>
              <span className="text-xs font-mono tracking-widest text-pink-400 uppercase block mb-2">
                QUANTIFIABLE BUSINESS IMPACT
              </span>
              <h2 className="text-3xl sm:text-4xl font-orbitron font-bold text-white mb-4 leading-tight">
                Compress Coordination Tax & Downtime
              </h2>
              <p className="text-sm text-purple-200/70 leading-relaxed">
                Calculate the downtime hours saved and revenue protected across your manufacturing lines by deploying NOVUS ADOS.
              </p>
            </div>

            <div className="p-6 rounded-2xl jarvis-glass-card border border-purple-500/30 flex items-center justify-between">
              <div>
                <span className="text-xs font-mono text-purple-300/70 block">Average Human Coordination Tax</span>
                <h4 className="text-xl font-orbitron font-bold text-red-400 mt-1">
                  4.2 Hours <span className="text-xs text-white">per Incident</span>
                </h4>
              </div>
              <div className="w-12 h-12 rounded-xl bg-red-500/20 border border-red-500/40 flex items-center justify-center text-xl">
                ⏱️
              </div>
            </div>

            <div className="p-6 rounded-2xl jarvis-glass-card border border-purple-500/30 flex items-center justify-between">
              <div>
                <span className="text-xs font-mono text-purple-300/70 block">NOVUS ADOS Compressed MTTR</span>
                <h4 className="text-xl font-orbitron font-bold text-emerald-400 mt-1">
                  39 Minutes <span className="text-xs text-white">(-84% Reduction)</span>
                </h4>
              </div>
              <div className="w-12 h-12 rounded-xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-xl">
                🚀
              </div>
            </div>
          </div>

          {/* Right Column: Interactive Impact Calculator Widget */}
          <div className="lg:col-span-7 p-8 rounded-3xl jarvis-glass-card border border-pink-500/30 bg-[#0c0824]/90 backdrop-blur-xl shadow-2xl">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-purple-500/20">
              <div>
                <span className="text-xs font-mono text-purple-300/60 uppercase">Monthly Plant Defect Volume</span>
                <h3 className="text-2xl font-orbitron font-bold text-white jarvis-pink-glow">
                  {monthlyIncidents} <span className="text-pink-400 font-syne">Incidents / Month</span>
                </h3>
              </div>
            </div>

            {/* Sliders */}
            <div className="space-y-6 mb-8">
              <div>
                <div className="flex justify-between items-center text-sm font-mono mb-2">
                  <span className="text-purple-200/80">Monthly Incident Volume:</span>
                  <span className="text-pink-400 font-bold">{monthlyIncidents} Incidents</span>
                </div>
                <input
                  type="range"
                  min="5"
                  max="150"
                  step="5"
                  value={monthlyIncidents}
                  onChange={(e) => setMonthlyIncidents(Number(e.target.value))}
                  className="w-full h-3 bg-purple-950/80 rounded-lg appearance-none cursor-pointer accent-pink-500 border border-purple-500/30"
                />
              </div>

              <div>
                <div className="flex justify-between items-center text-sm font-mono mb-2">
                  <span className="text-purple-200/80">Active Factory Production Lines:</span>
                  <span className="text-cyan-400 font-bold">{factoryLines} Lines</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="20"
                  step="1"
                  value={factoryLines}
                  onChange={(e) => setFactoryLines(Number(e.target.value))}
                  className="w-full h-3 bg-purple-950/80 rounded-lg appearance-none cursor-pointer accent-cyan-400 border border-purple-500/30"
                />
              </div>
            </div>

            {/* Calculations */}
            <div className="grid grid-cols-3 gap-4 p-5 rounded-2xl bg-purple-950/50 border border-purple-500/20 mb-8 text-center">
              <div>
                <span className="text-[10px] font-mono text-purple-300/60 block uppercase">Downtime Saved</span>
                <span className="text-xl font-orbitron font-bold text-emerald-400">
                  {totalDowntimeHoursSaved} hrs
                </span>
              </div>
              <div>
                <span className="text-[10px] font-mono text-purple-300/60 block uppercase">Revenue Protected</span>
                <span className="text-xl font-orbitron font-bold text-cyan-400">
                  ${ProtectedRevenue}K
                </span>
              </div>
              <div>
                <span className="text-[10px] font-mono text-purple-300/60 block uppercase">Tier-0 Autonomy Ratio</span>
                <span className="text-xl font-orbitron font-bold text-pink-400">
                  {autonomousRatio}%
                </span>
              </div>
            </div>

            {/* Action CTA */}
            <Link
              href="/executive/enterprise"
              className="block w-full text-center py-4 rounded-2xl jarvis-btn-primary font-orbitron font-bold text-sm tracking-wider text-white shadow-2xl shadow-pink-500/40 hover:scale-[1.02] transition-transform"
            >
              OPEN EXECUTIVE INTELLIGENCE DASHBOARD
            </Link>
          </div>
        </div>
      </section>

      {/* ==================== 7. FOOTER ==================== */}
      <footer className="relative z-20 border-t border-purple-500/20 bg-[#04030d] py-12 text-xs font-mono text-purple-300/60">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-pink-500/20 border border-pink-500/40 flex items-center justify-center font-orbitron font-bold text-white text-xs">
              N
            </div>
            <div>
              <span className="font-orbitron font-bold text-white text-sm">NOVUS ADOS</span>
              <p className="text-[10px] text-purple-300/40">Autonomous Defect & Orchestration System</p>
            </div>
          </div>

          <div className="flex items-center gap-6">
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              NOVUS AI CORE: ONLINE
            </span>
            <span className="hidden sm:inline">•</span>
            <span>CLOUDANT RAG: ACTIVE</span>
            <span className="hidden sm:inline">•</span>
            <span>watsonx ITSM: CONNECTED</span>
          </div>

          <p className="text-[10px] text-purple-300/40">
            © 2026 NOVUS ADOS. All rights reserved.
          </p>
        </div>
      </footer>
    </div>
  );
}
