"use client";

import React, { useState } from "react";

interface FeatureItem {
  id: string;
  menuTitle: string;
  cardTitle: string;
  badge: string;
  description: string;
  metaLeft: string;
  metaRight: string;
  icon: string;
  gradientClass: string;
  shadowClass: string;
}

export function ActiveTheoryFeaturesShowcase() {
  const [activeIndex, setActiveIndex] = useState(0);

  const features: FeatureItem[] = [
    {
      id: "agents",
      menuTitle: "8 SPECIALIST AI AGENTS",
      cardTitle: "SPECIALIST AGENTS",
      badge: "LAYER 2 AGENTS",
      description: "VisionSpec, CAD Comparison, Causal Isolation, Inventory Substitution, Parameter Shift, and Impact Simulation agents reasoning in parallel.",
      metaLeft: "SYSTEM: PARALLEL",
      metaRight: "THREAD_COUNT: 8",
      icon: "👁️",
      gradientClass: "from-pink-600/35 via-purple-900/30 to-black/80",
      shadowClass: "shadow-[0_0_40px_rgba(236,72,153,0.25)] border-pink-500/40",
    },
    {
      id: "governance",
      menuTitle: "TIERED GOVERNANCE",
      cardTitle: "AUTONOMY GOVERNANCE",
      badge: "SAFETY ENGINE",
      description: "Tier 0 (Autonomous Execution for high confidence), Tier 1 (Plant Manager Queue), and Tier 2 (Executive Safety Lock).",
      metaLeft: "INTEGRITY: SECURE",
      metaRight: "EARNED TRUST",
      icon: "🛡️",
      gradientClass: "from-purple-600/35 via-indigo-900/30 to-black/80",
      shadowClass: "shadow-[0_0_40px_rgba(168,85,247,0.25)] border-purple-500/40",
    },
    {
      id: "hub",
      menuTitle: "CAPABILITY HUB",
      cardTitle: "CAPABILITY ORCHESTRATION",
      badge: "LAYER 4 HUB",
      description: "Executes via abstract capabilities (ReserveInventory, CreateIncident) across SAP & ServiceNow without vendor lock-in.",
      metaLeft: "INTEGRATION: ACTIVE",
      metaRight: "ZERO VENDOR LOCK",
      icon: "⚡",
      gradientClass: "from-cyan-600/35 via-blue-900/30 to-black/80",
      shadowClass: "shadow-[0_0_40px_rgba(6,182,212,0.25)] border-cyan-500/40",
    },
    {
      id: "rag",
      menuTitle: "CAUSAL LEARNING RAG",
      cardTitle: "CAUSAL LEARNING",
      badge: "BAYESIAN GRAPH",
      description: "IBM Cloudant NoSQL Decision Memory indexes past incident outcomes to recalibrate Bayesian causal graph edge weights over time.",
      metaLeft: "RAG_STORE: CLOUDANT",
      metaRight: "MEMORY_INDEXED",
      icon: "🧠",
      gradientClass: "from-emerald-600/35 via-teal-900/30 to-black/80",
      shadowClass: "shadow-[0_0_40px_rgba(16,185,129,0.25)] border-emerald-500/40",
    },
    {
      id: "twin",
      menuTitle: "DIGITAL TWIN MODEL",
      cardTitle: "DIGITAL TWIN",
      badge: "EAM DATASET",
      description: "Enterprise Asset Model (Plant > Factory > Line > Machine > PLC > Sensor) tracking live physical telemetry & inventory soft locks.",
      metaLeft: "TWIN_SYNC: REAL-TIME",
      metaRight: "ACTIVE_SENSORS",
      icon: "🏭",
      gradientClass: "from-amber-600/35 via-orange-900/30 to-black/80",
      shadowClass: "shadow-[0_0_40px_rgba(245,158,11,0.25)] border-amber-500/40",
    },
    {
      id: "executive",
      menuTitle: "EXECUTIVE INTEL",
      cardTitle: "EXECUTIVE DASHBOARD",
      badge: "LAYER 6 KPI",
      description: "C-suite KPIs measuring MTTR compression, protected revenue at risk, supplier quality risk scores, and evidence-grounded Copilot.",
      metaLeft: "DEFENSE: ACTIVE",
      metaRight: "REVENUE_PROTECTED",
      icon: "📈",
      gradientClass: "from-rose-600/35 via-red-900/30 to-black/80",
      shadowClass: "shadow-[0_0_40px_rgba(244,63,94,0.25)] border-rose-500/40",
    },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 items-center min-h-[500px] w-full mt-10">
      {/* Left Navigation Menu (Active Theory Style) */}
      <div className="lg:col-span-5 flex flex-col justify-center space-y-8 select-none">
        <div>
          <h4 className="text-xs font-mono tracking-widest text-pink-500 uppercase mb-2">
            SYSTEM DISCOVERY
          </h4>
          <h3 className="text-2xl sm:text-3xl font-orbitron font-extrabold text-white tracking-wider">
            WHAT PORTION ARE YOU EXPLORING?
          </h3>
        </div>

        <nav className="flex flex-col space-y-4">
          {features.map((feature, idx) => {
            const isActive = idx === activeIndex;
            return (
              <button
                key={feature.id}
                onClick={() => setActiveIndex(idx)}
                onMouseEnter={() => setActiveIndex(idx)}
                className={`text-left font-orbitron font-bold text-sm tracking-widest flex items-center transition-all duration-300 ${
                  isActive
                    ? "text-white translate-x-3 text-shadow-[0_0_10px_rgba(236,72,153,0.5)]"
                    : "text-purple-300/40 hover:text-purple-200/80 hover:translate-x-1"
                }`}
              >
                <span className={`mr-3 font-mono transition-transform ${isActive ? "text-pink-500" : "opacity-30"}`}>
                  -&gt;
                </span>
                {feature.menuTitle}
              </button>
            );
          })}
        </nav>

        {/* Bottom capsule CTA button */}
        <div className="pt-4">
          <button
            onClick={() => {
              // Click action or trigger lab modal
              const modalBtn = document.querySelector('[data-lab-trigger="true"]');
              if (modalBtn instanceof HTMLButtonElement) modalBtn.click();
            }}
            className="px-6 py-3 rounded-full border border-purple-500/40 bg-[#0c0824]/60 font-orbitron font-bold text-xs tracking-wider text-purple-200 hover:text-white hover:border-pink-500/60 shadow-lg hover:shadow-pink-500/10 transition-all flex items-center gap-2 max-w-max cursor-pointer"
          >
            <span>ASK ME ANYTHING...</span>
          </button>
        </div>
      </div>

      {/* Right Angled 3D Showcasing Canvas (Active Theory Style) */}
      <div className="lg:col-span-7 relative h-[420px] flex items-center justify-center overflow-hidden">
        {/* Animated Background particle vortex backdrop */}
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(168,85,247,0.1),transparent_70%)] animate-pulse" />

        {features.map((feature, idx) => {
          const offset = idx - activeIndex;
          const isActive = idx === activeIndex;

          // Compute 3D transformation values to match floating stacked 3D cards
          let transformStyle = "";
          let opacityStyle = 0;
          let zIndex = 0;
          let blurStyle = "blur-none";

          if (isActive) {
            transformStyle = "perspective(1000px) rotateY(-18deg) scale(1.05) translateZ(50px)";
            opacityStyle = 1;
            zIndex = 30;
            blurStyle = "blur-none";
          } else if (offset === 1 || (offset === -5 && activeIndex === 0)) {
            // First stack card to the right
            transformStyle = "perspective(1000px) rotateY(-22deg) scale(0.9) translateX(120px) translateZ(-50px)";
            opacityStyle = 0.5;
            zIndex = 20;
            blurStyle = "blur-[2px]";
          } else if (offset === -1 || (offset === 5 && activeIndex === 5)) {
            // First stack card to the left
            transformStyle = "perspective(1000px) rotateY(-12deg) scale(0.9) translateX(-120px) translateZ(-50px)";
            opacityStyle = 0.3;
            zIndex = 10;
            blurStyle = "blur-[3px]";
          } else {
            // Far back cards
            transformStyle = "perspective(1000px) rotateY(-15deg) scale(0.8) translateZ(-150px) opacity-0 pointer-events-none";
            opacityStyle = 0;
            zIndex = 0;
          }

          return (
            <div
              key={feature.id}
              style={{
                transform: transformStyle,
                opacity: opacityStyle,
                zIndex: zIndex,
              }}
              className={`absolute w-full max-w-[420px] aspect-[4/3] rounded-3xl p-8 bg-gradient-to-br ${feature.gradientClass} border ${feature.shadowClass} flex flex-col justify-between transition-all duration-700 ease-out select-none ${blurStyle}`}
            >
              {/* Scanline overlay for high-tech aesthetic */}
              <div className="absolute inset-0 rounded-3xl cyber-scanline opacity-20 pointer-events-none" />

              {/* Card Corner brackets */}
              <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-white/30 rounded-tl-3xl pointer-events-none" />
              <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-white/30 rounded-tr-3xl pointer-events-none" />
              <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-white/30 rounded-bl-3xl pointer-events-none" />
              <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-white/30 rounded-br-3xl pointer-events-none" />

              {/* Top Meta Telemetry */}
              <div className="flex items-center justify-between text-[10px] font-mono text-purple-300/70 border-b border-white/10 pb-4">
                <span className="font-bold uppercase tracking-wider">{feature.badge}</span>
                <span className="bg-purple-950/40 px-2 py-0.5 rounded border border-purple-500/20 text-cyan-400">
                  ADOS_SYS
                </span>
              </div>

              {/* Central Project Title & Description */}
              <div className="my-auto py-2">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-3xl">{feature.icon}</span>
                  <h3 className="text-2xl font-orbitron font-black tracking-widest text-white uppercase leading-tight">
                    {feature.cardTitle}
                  </h3>
                </div>
                <p className="text-sm text-purple-200/80 leading-relaxed font-sans mt-3">
                  {feature.description}
                </p>
              </div>

              {/* Bottom Meta Telemetry */}
              <div className="flex items-center justify-between text-[9px] font-mono text-purple-400/60 border-t border-white/10 pt-4 uppercase tracking-widest">
                <span>{feature.metaLeft}</span>
                <span>{feature.metaRight}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
