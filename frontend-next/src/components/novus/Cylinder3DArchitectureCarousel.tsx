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
}

export function Cylinder3DArchitectureCarousel() {
  const [rotationAngle, setRotationAngle] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);
  const [isAutoSpin, setIsAutoSpin] = useState(true);

  const layers: LayerItem[] = [
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
    },
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

  const radius = 280; // Distance of cards from center of 3D cylinder

  return (
    <div className="relative w-full min-h-[580px] py-12 flex flex-col items-center justify-center overflow-hidden select-none">
      {/* Millanova Style Background Radial Ray Stripes */}
      <div className="absolute inset-0 opacity-15 pointer-events-none">
        <div className="w-full h-full bg-[repeating-conic-gradient(from_0deg,#3b0764_0deg_15deg,#070514_15deg_30deg)] blur-[3px]" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#070514] via-transparent to-[#070514]" />
      </div>

      {/* Main 3D Scene Wrapper */}
      <div className="relative w-full max-w-[900px] h-[380px] flex items-center justify-center">
        {/* Removed Floating circular button for cleaner layout */}

        {/* 3D Perspective Cylinder Container */}
        <div
          style={{
            perspective: "1200px",
            perspectiveOrigin: "50% 30%",
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
                  className={`absolute inset-0 rounded-2xl border bg-gradient-to-b ${
                    layer.bgGrad
                  } ${layer.color} p-6 flex flex-col justify-between cursor-pointer transition-all duration-500 ${
                    isCurrent
                      ? "scale-105 opacity-100 shadow-[0_0_50px_rgba(6,182,212,0.35)] ring-2 ring-cyan-400/80"
                      : "opacity-35 hover:opacity-70 scale-95"
                  }`}
                >
                  {/* Cyber Scanline Overlay */}
                  <div className="absolute inset-0 rounded-2xl cyber-scanline opacity-10 pointer-events-none" />

                  {/* Corner Tick Decoration */}
                  <div className="absolute top-0 left-0 w-3 h-3 border-t border-l border-white/40 rounded-tl-2xl pointer-events-none" />
                  <div className="absolute top-0 right-0 w-3 h-3 border-t border-r border-white/40 rounded-tr-2xl pointer-events-none" />
                  <div className="absolute bottom-0 left-0 w-3 h-3 border-b border-l border-white/40 rounded-bl-2xl pointer-events-none" />
                  <div className="absolute bottom-0 right-0 w-3 h-3 border-b border-r border-white/40 rounded-br-2xl pointer-events-none" />

                  {/* Editorial Layout: Large Vertical Layer Header */}
                  <div className="flex justify-between items-start">
                    <span className={`text-4xl font-black font-orbitron tracking-tight leading-none ${layer.textColor}`}>
                      {layer.layer}
                    </span>
                    <span className="text-[10px] font-mono tracking-widest text-cyan-300/80 uppercase font-bold">
                      DECISION_STK
                    </span>
                  </div>

                  {/* Editorial Title & Description */}
                  <div className="my-auto py-4">
                    <h3 className="text-base font-orbitron font-extrabold text-white tracking-wide uppercase leading-tight mb-2">
                      {layer.name}
                    </h3>
                    <p className="text-[12px] text-slate-200 leading-relaxed font-sans font-medium">
                      {layer.desc}
                    </p>
                  </div>

                  {/* Technical Sub-Details list */}
                  <div className="border-t border-white/20 pt-3 space-y-1.5">
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

      {/* Bottom Selector Indicators */}
      <div className="flex items-center justify-center gap-3 mt-6 z-20">
        <button
          onClick={rotateLeft}
          className="px-3 py-1.5 rounded-lg border border-purple-500/20 bg-purple-950/40 text-xs font-mono text-purple-300 hover:text-white hover:border-pink-500/50 transition-colors"
        >
          &lt; PREV
        </button>
        <div className="flex items-center gap-2">
          {layers.map((_, idx) => (
            <button
              key={idx}
              onClick={() => selectLayer(idx)}
              className={`w-2 h-2 rounded-full transition-all duration-300 ${
                idx === activeIndex ? "bg-pink-500 w-5" : "bg-purple-500/30 hover:bg-purple-500/60"
              }`}
            />
          ))}
        </div>
        <button
          onClick={rotateRight}
          className="px-3 py-1.5 rounded-lg border border-purple-500/20 bg-purple-950/40 text-xs font-mono text-purple-300 hover:text-white hover:border-pink-500/50 transition-colors"
        >
          NEXT &gt;
        </button>
        <button
          onClick={() => setIsAutoSpin((prev) => !prev)}
          className={`px-3 py-1.5 rounded-lg border text-xs font-mono tracking-wider transition-all duration-300 ${
            isAutoSpin
              ? "border-pink-500/50 bg-pink-950/40 text-pink-400 shadow-[0_0_15px_rgba(236,72,153,0.15)]"
              : "border-purple-500/20 bg-purple-950/40 text-purple-400 hover:text-white"
          }`}
        >
          {isAutoSpin ? "AUTO: ON" : "AUTO: OFF"}
        </button>
      </div>
    </div>
  );
}
