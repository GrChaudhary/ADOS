"use client";

import React from "react";

interface NovusHeaderIconProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function NovusHeaderIcon({ size = "md", className = "" }: NovusHeaderIconProps) {
  const dimensions = {
    sm: "w-8 h-8",
    md: "w-10 h-10",
    lg: "w-12 h-12",
  }[size];

  return (
    <div className={`relative group cursor-pointer ${dimensions} ${className}`}>
      {/* Background ambient glow effect */}
      <div className="absolute -inset-1 rounded-2xl bg-gradient-to-r from-pink-500 via-purple-600 to-cyan-400 blur-md opacity-75 group-hover:opacity-100 transition-all duration-500 group-hover:scale-110" />

      {/* Main Glass Icon Container */}
      <div className="relative w-full h-full rounded-2xl bg-[#0b0726] border border-purple-500/50 flex items-center justify-center shadow-2xl overflow-hidden backdrop-blur-xl group-hover:border-pink-500/80 transition-colors">
        {/* Animated Background Mesh Rays */}
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_50%,rgba(236,72,153,0.25),transparent_70%)] animate-pulse" />

        {/* Custom Sci-Fi Hex / Neural AI Vector Icon */}
        <svg
          viewBox="0 0 40 40"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-full p-1.5 relative z-10 transition-transform duration-300 group-hover:scale-105"
        >
          <defs>
            <linearGradient id="novusGradient1" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ec4899" />
              <stop offset="50%" stopColor="#c084fc" />
              <stop offset="100%" stopColor="#38bdf8" />
            </linearGradient>

            <linearGradient id="novusGradient2" x1="100%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#38bdf8" />
              <stop offset="100%" stopColor="#d946ef" />
            </linearGradient>

            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.5" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Outer Sci-Fi Hexagon Frame */}
          <polygon
            points="20,4 34,12 34,28 20,36 6,28 6,12"
            stroke="url(#novusGradient1)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-90"
          />

          {/* Inner Corner Nodes */}
          <circle cx="20" cy="4" r="1.5" fill="#f472b6" />
          <circle cx="34" cy="12" r="1.5" fill="#38bdf8" />
          <circle cx="34" cy="28" r="1.5" fill="#c084fc" />
          <circle cx="20" cy="36" r="1.5" fill="#ec4899" />
          <circle cx="6" cy="28" r="1.5" fill="#38bdf8" />
          <circle cx="6" cy="12" r="1.5" fill="#f472b6" />

          {/* Stylized 'N' Apex & Decision Lattice */}
          <path
            d="M13,27 V13 L27,27 V13"
            stroke="url(#novusGradient2)"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            filter="url(#glow)"
          />

          {/* Center Glowing Decision Node Dot */}
          <circle cx="20" cy="20" r="2.5" fill="#ffffff" className="animate-ping opacity-80" />
          <circle cx="20" cy="20" r="2" fill="#ec4899" filter="url(#glow)" />
        </svg>
      </div>
    </div>
  );
}
