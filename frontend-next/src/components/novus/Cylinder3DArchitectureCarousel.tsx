"use client";

import React, { useState, useEffect } from "react";

interface LayerItem {
  id: string;
  layer: string;
  name: string;
  desc: string;
  details: string[];
  color: string;
  textColor: string;
  accentColor: string;
  bgGrad: string;
  icon: string;
}

export function Cylinder3DArchitectureCarousel() {
  const [rotationAngle, setRotationAngle] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isAutoSpin, setIsAutoSpin] = useState(true);

  const layers: LayerItem[] = [
    {
      id: "l1",
      layer: "L1",
      name: "Event Bus & Envelope",
      desc: "Redis & In-Memory pub/sub event envelope distribution.",
      details: ["Redis Pub/Sub Event Bus", "Payload Schema Validation", "Microsecond Latency Bus"],
      color: "border-blue-500/40 shadow-blue-500/10",
      textColor: "text-blue-400",
      accentColor: "#3b82f6",
      bgGrad: "from-blue-950/80 via-indigo-950/40 to-black/90",
      icon: "⚡",
    },
    {
      id: "l2",
      layer: "L2",
      name: "Specialist AI Agents",
      desc: "VisionSpec, CAD Comparison, Causal Isolation, and Parameter Shift agents.",
      details: ["VisionSpec Detection Core", "CAD Vector Comparison", "Causal Path Isolation"],
      color: "border-amber-500/40 shadow-amber-500/10",
      textColor: "text-amber-400",
      accentColor: "#f59e0b",
      bgGrad: "from-amber-950/80 via-orange-950/40 to-black/90",
      icon: "🤖",
    },
    {
      id: "l3",
      layer: "L3",
      name: "Decision Memory",
      desc: "Cloudant NoSQL RAG precedent vectors and Bayesian Causal Graph Recalibration.",
      details: ["Cloudant Precedent Vector DB", "Causal Weight Calibration", "Precedent Indexing"],
      color: "border-emerald-500/40 shadow-emerald-500/10",
      textColor: "text-emerald-400",
      accentColor: "#10b981",
      bgGrad: "from-emerald-950/80 via-teal-950/40 to-black/90",
      icon: "🧠",
    },
    {
      id: "l4",
      layer: "L4",
      name: "Decision Orchestrator",
      desc: "Multistage State Machine, ServiceNow ITSM, SAP ERP, and B2B Marketplaces.",
      details: ["SAP ERP RFC Connectors", "ServiceNow Incident Hub", "State Machine Core"],
      color: "border-cyan-500/40 shadow-cyan-500/10",
      textColor: "text-cyan-400",
      accentColor: "#06b6d4",
      bgGrad: "from-cyan-950/80 via-blue-950/40 to-black/90",
      icon: "⚙️",
    },
    {
      id: "l5",
      layer: "L5",
      name: "Governance Engine",
      desc: "Tier 0 Autonomous, Tier 1 Plant Manager Queue, and Tier 2 Executive Safety Lock.",
      details: ["Autonomy Tier Control", "Precedent Verdicts", "Lock-out Protocols"],
      color: "border-purple-500/40 shadow-purple-500/10",
      textColor: "text-purple-400",
      accentColor: "#a855f7",
      bgGrad: "from-purple-950/80 via-indigo-950/40 to-black/90",
      icon: "🛡️",
    },
    {
      id: "l6",
      layer: "L6",
      name: "Executive Intel",
      desc: "C-suite Revenue at Risk, MTTR KPIs, and Watsonx Copilot integrations.",
      details: ["Watsonx.ai Copilot", "Protected Revenue Index", "MTTR Analytics Engine"],
      color: "border-pink-500/40 shadow-pink-500/10",
      textColor: "text-pink-400",
      accentColor: "#ec4899",
      bgGrad: "from-pink-950/80 via-purple-950/40 to-black/90",
      icon: "📊",
    },
  ];

  const rotateLeft = () => {
    setRotationAngle((prev) => prev + 60);
    setActiveIndex((prev) => (prev === 0 ? 5 : prev - 1));
  };

  const rotateRight = () => {
    setRotationAngle((prev) => prev - 60);
    setActiveIndex((prev) => (prev === 5 ? 0 : prev + 1));
  };

  const selectLayer = (index: number) => {
    const diff = index - activeIndex;
    setRotationAngle((prev) => prev - diff * 60);
    setActiveIndex(index);
  };

  // Auto spin timer logic
  useEffect(() => {
    if (!isAutoSpin) return;
    const interval = setInterval(() => {
      rotateRight();
    }, 3800);
    return () => clearInterval(interval);
  }, [isAutoSpin, activeIndex]);

  const radius = 300; // Distance of cards from center of 3D cylinder

  return (
    <div className="relative w-full min-h-[640px] py-12 flex flex-col items-center justify-center overflow-hidden select-none">
      {/* Millanova Style Background Radial Ray Stripes */}
      <div className="absolute inset-0 pointer-events-none opacity-20 bg-[radial-gradient(circle_at_center,rgba(168,85,247,0.15)_0%,transparent_70%)]" />

      <div className="relative w-full h-[440px] flex items-center justify-center">
        {/* 3D Perspective Cylinder Container */}
        <div
          style={{
            perspective: "1200px",
            perspectiveOrigin: "50% 35%",
          }}
          className="w-full h-full flex items-center justify-center"
        >
          {/* Rotating Ring */}
          <div
            style={{
              transformStyle: "preserve-3d",
              transform: `rotateY(${rotationAngle}deg)`,
              transition: "transform 1.2s cubic-bezier(0.16, 1, 0.3, 1)",
            }}
            className="relative w-[230px] h-[340px]"
          >
            {layers.map((layer, index) => {
              const angle = index * 60; // 360 / 6 = 60 degrees
              const isCurrent = index === activeIndex;

              return (
                <div
                  key={layer.id}
                  onClick={() => selectLayer(index)}
                  style={{
                    transformStyle: "preserve-3d",
                    transform: `rotateY(${angle}deg) translateZ(${radius}px)`,
                    backfaceVisibility: "hidden",
                  }}
                  className={`absolute inset-0 rounded-2xl border bg-gradient-to-b overflow-hidden backdrop-blur-xl saturate-150 ${
                    layer.bgGrad
                  } ${layer.color} p-6 flex flex-col justify-between cursor-pointer transition-all duration-500 ${
                    isCurrent
                      ? "scale-105 opacity-100 shadow-[0_0_35px_rgba(6,182,212,0.4)] ring-2 ring-cyan-400/80 z-30"
                      : "opacity-40 hover:opacity-80 scale-95 z-10"
                  }`}
                >
                  {/* Liquid Glass Dynamic Sheen Highlight */}
                  <div className="absolute inset-0 bg-gradient-to-br from-white/20 via-white/5 to-transparent opacity-60 pointer-events-none rounded-2xl" />
                  <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-bl from-cyan-400/20 to-transparent blur-xl pointer-events-none" />

                  {/* Cyber Scanline Overlay */}
                  <div className="absolute inset-0 rounded-2xl cyber-scanline opacity-10 pointer-events-none" />

                  {/* Corner Tick Decoration */}
                  <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-white/40 rounded-tl-2xl pointer-events-none" />
                  <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-white/40 rounded-tr-2xl pointer-events-none" />
                  <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-white/40 rounded-bl-2xl pointer-events-none" />
                  <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-white/40 rounded-br-2xl pointer-events-none" />

                  {/* Editorial Layout: Large Vertical Layer Header & Illuminated 3D Glass Icon */}
                  <div className="flex justify-between items-start relative z-10">
                    <div className="flex items-center gap-2">
                      <span className={`text-4xl font-black font-orbitron tracking-tight leading-none ${layer.textColor}`}>
                        {layer.layer}
                      </span>
                      {/* Illuminated Liquid 3D Glass Icon */}
                      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-white/20 to-white/5 border border-white/30 backdrop-blur-md flex items-center justify-center text-sm shadow-[0_0_12px_rgba(255,255,255,0.2)]">
                        {layer.icon}
                      </div>
                    </div>
                    <span className="text-[10px] font-mono tracking-widest text-cyan-300/80 uppercase font-bold">
                      DECISION_STK
                    </span>
                  </div>

                  {/* Editorial Title & Description */}
                  <div className="my-auto py-3 relative z-10">
                    <h3 className="text-base font-orbitron font-extrabold text-white tracking-wide uppercase leading-tight mb-1.5">
                      {layer.name}
                    </h3>
                    <p className="text-[12px] text-slate-200 leading-relaxed font-sans font-medium">
                      {layer.desc}
                    </p>
                  </div>

                  {/* Technical Sub-Details list */}
                  <div className="border-t border-white/20 pt-3 space-y-1.5 relative z-10">
                    {layer.details.map((detail, dIdx) => (
                      <div key={dIdx} className="flex items-center gap-2 text-[10px] font-mono text-cyan-200 font-medium">
                        <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_#06b6d4]" />
                        <span>{detail}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Bottom Selector Indicators & AUTO SPIN Button */}
      <div className="relative flex flex-wrap items-center justify-center gap-3 mt-20 z-20">
        <button
          onClick={rotateLeft}
          className="px-4 py-2 rounded-xl border border-purple-500/30 bg-purple-950/60 text-xs font-mono text-purple-300 hover:text-white hover:border-pink-500/60 transition-all shadow-lg cursor-pointer"
        >
          &lt; PREV
        </button>

        <div className="flex items-center gap-2">
          {layers.map((l, i) => (
            <button
              key={l.id}
              onClick={() => selectLayer(i)}
              className={`w-3 h-3 rounded-full transition-all cursor-pointer ${
                i === activeIndex
                  ? "bg-cyan-400 w-8 shadow-[0_0_10px_#06b6d4]"
                  : "bg-white/20 hover:bg-white/40"
              }`}
            />
          ))}
        </div>

        <button
          onClick={rotateRight}
          className="px-4 py-2 rounded-xl border border-purple-500/30 bg-purple-950/60 text-xs font-mono text-purple-300 hover:text-white hover:border-pink-500/60 transition-all shadow-lg cursor-pointer"
        >
          NEXT &gt;
        </button>

        {/* AUTO Toggle Button */}
        <button
          onClick={() => setIsAutoSpin(!isAutoSpin)}
          className={`px-4 py-2 rounded-xl border text-xs font-mono transition-all shadow-lg cursor-pointer flex items-center gap-2 ${
            isAutoSpin
              ? "bg-cyan-500/20 border-cyan-400 text-cyan-300 shadow-[0_0_15px_rgba(6,182,212,0.3)]"
              : "bg-white/5 border-white/20 text-slate-400 hover:text-white"
          }`}
        >
          <span className={`w-2 h-2 rounded-full ${isAutoSpin ? "bg-cyan-400 animate-ping" : "bg-slate-500"}`} />
          <span>AUTO: {isAutoSpin ? "ON" : "OFF"}</span>
        </button>
      </div>
    </div>
  );
}
